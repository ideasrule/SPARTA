from astropy.io import fits
import sys
import matplotlib.pyplot as plt
import numpy as np
from numpy.polynomial.chebyshev import chebval
import scipy.linalg
import os.path
import pdb
from constants import HIGH_ERROR, LEFT_MARGIN, EXTRACT_Y_MIN, EXTRACT_Y_MAX, OPT_EXTRACT_WINDOW, SLITLESS_TOP, SLITLESS_BOT, BAD_GRPS, WCS_FILE, BKD_WIDTH
from scipy.stats import median_abs_deviation

def fit_spectrum(image_row, spectrum, weights, num_ord=5):
    cols = np.arange(len(spectrum))
    xs = (cols - np.mean(cols))/len(cols) * 2
    A = []
    for o in range(num_ord):
        cheby_coeffs = np.zeros(o + 1)
        cheby_coeffs[o] = 1
        cheby = chebval(xs, cheby_coeffs)
        A.append(spectrum * cheby)

    A = np.array(A).T
    Aw = A * np.sqrt(weights[:, np.newaxis])
    Bw = image_row * np.sqrt(weights)
    coeffs, residuals, rank, s = scipy.linalg.lstsq(Aw, Bw)    
    predicted = Aw.dot(coeffs)
    smoothed_profile = chebval(xs, coeffs)
    #plt.plot(image_row)
    #plt.plot(predicted / np.sqrt(weights))
    #plt.show()
    
    return smoothed_profile

def horne_iteration(image, bkd, spectrum, M, V, badpix, flat_err, read_noise, n_groups_used, smoothed_profile, sigma=4):
    #N is the number of groups used, minus one
    V[image == 0] = HIGH_ERROR**2 
    cols = np.arange(image.shape[1])
    
    model_image = smoothed_profile * spectrum
    l = np.arccosh(1 + np.abs(model_image + bkd) / read_noise**2 / 2)
    N = n_groups_used - 1
    V = 1 / (read_noise**-2 * np.exp(l) * (-N*np.exp(-l*N) + np.exp(2*l)*N + np.exp(l-l*N)*(2+N) - np.exp(l)*(2+N)) / (np.exp(l) - 1)**3 / (np.exp(-l*N) + np.exp(l)))
    V += ((model_image + bkd) * flat_err)**2
    V[badpix] = HIGH_ERROR**2

    #plt.figure(0, figsize=(18,3))
    #plt.clf() 
    #plt.imshow(badpix, aspect='auto')
    #plt.show()

    z_scores = (image - model_image)/np.sqrt(V)
    M = np.array(z_scores**2 < sigma**2, dtype=bool)
    V[~M] = HIGH_ERROR**2
    original_spectrum = np.copy(spectrum)
    spectrum = np.sum(smoothed_profile * image / V, axis=0) / np.sum(smoothed_profile**2 / V, axis=0)
    spectrum_variance = np.sum(smoothed_profile, axis=0) / np.sum(smoothed_profile**2 / V, axis=0)

    #import pdb
    #pdb.set_trace()
    '''plt.imshow(z_scores, vmin=-5, vmax=5, aspect='auto')
    plt.figure()
    plt.imshow(M)
    plt.show()'''
    
    return spectrum, spectrum_variance, V, M, z_scores

def optimal_extract(image, bkd, badpix, flat_err, read_noise, n_groups_used, P, max_iter=10):
    #plt.imshow(image, aspect='auto', vmin=0, vmax=20)
    #plt.show()
    
    if badpix is None:
        badpix = np.zeros(image.shape, dtype=bool)
    print("Num badpix", np.sum(badpix))
        
    spectrum = np.sum(image, axis=0)
    simple_spectrum = np.copy(spectrum)
    
    V = np.ones(image.shape)
    M = np.ones(image.shape, dtype=bool)
    counter = 0
    
    while True:        
        spectrum, spectrum_variance, V, new_M, z_scores = horne_iteration(image, bkd, spectrum, M, V, badpix, flat_err, read_noise, n_groups_used, P)
        #plt.figure(figsize=(16,16))
        #plt.imshow(z_scores, vmin=-10, vmax=10)
        #plt.figure()
        
        print("Iter, num bad:", counter, np.sum(~new_M))
        if np.all(M == new_M) or counter > max_iter: break
        M = new_M
        counter += 1
    print("Final std of z_scores (should be around 1)", np.std(z_scores[M]))
    return spectrum, spectrum_variance, z_scores, simple_spectrum

def get_wavelengths():
    with fits.open(WCS_FILE) as hdul:
        all_ys = np.arange(SLITLESS_TOP, SLITLESS_BOT)
        wavelengths = np.interp(all_ys,
                                (hdul[0].header["IMYSLTL"] + hdul[1].data["Y_CENTER"] - 1)[::-1],
                                hdul[1].data["WAVELENGTH"][::-1])
        return wavelengths

def get_profile(filename="median_image.npy"):
    median_image = np.load(filename)[EXTRACT_Y_MIN:EXTRACT_Y_MAX, 36-OPT_EXTRACT_WINDOW : 36 + OPT_EXTRACT_WINDOW + 1]
    median_spectrum = np.sum(median_image, axis=1)
    P = median_image / median_spectrum[:,np.newaxis]
    #plt.imshow(P, aspect='auto')
    #plt.show()
    
    '''#Smooth profile
    rows = np.arange(P.shape[0])
    xs = rows / np.mean(rows) - 1
    for c in range(P.shape[1]):
        coeffs = np.polyfit(xs, P[:,c], 7)
        #plt.plot(P[:,c])
        P[:,c] = np.polyval(coeffs, xs)
        #plt.plot(P[:,c])
        #plt.show()'''
    
    P[P < 0] = 0
    P /= np.sum(P, axis=1)[:,np.newaxis]
    return P


print("Applying optimal extraction")
P = get_profile()    

#filename = sys.argv[1]

for filename in sys.argv[1:]:
    with fits.open(filename) as hdul:
        wavelengths = get_wavelengths()
        hdulist = [hdul[0], hdul["INT_TIMES"]]

        for i in range(len(hdul["SCI"].data)):
            print("Processing integration", i)

            data = hdul["SCI"].data[i][EXTRACT_Y_MIN:EXTRACT_Y_MAX]
            data[:, 0:LEFT_MARGIN] = 0

            bkd_cols = np.hstack([data[:, 10:25], data[:,47:62]])
            #bkd_cols = data[:,-15:]
            bkd = np.mean(bkd_cols, axis=1)
            profile = np.sum(data, axis=0)
            trace_loc = np.argmax(profile)
            s = np.s_[EXTRACT_Y_MIN:EXTRACT_Y_MAX, trace_loc - OPT_EXTRACT_WINDOW : trace_loc + OPT_EXTRACT_WINDOW + 1]

            spectrum, variance, z_scores, simple_spectrum = optimal_extract(
                (hdul["SCI"].data[i][s] - bkd[:,np.newaxis]).T,
                (hdul["SCI"].data[i][s]*0 + bkd[:,np.newaxis]).T,
                hdul["DQ"].data[i][s].T != 0,
                hdul["FLATERR"].data[s].T,
                hdul["RNOISE"].data[s].T,
                hdul[0].header["NGROUPS"] - BAD_GRPS,
                P.T
            )

            hdulist.append(fits.BinTableHDU.from_columns([
                fits.Column(name="WAVELENGTH", format="D", unit="um", array=wavelengths[EXTRACT_Y_MIN:EXTRACT_Y_MAX]),
                fits.Column(name="FLUX", format="D", unit="Electrons/group", array=spectrum),
                fits.Column(name="ERROR", format="D", unit="Electrons/group", array=np.sqrt(variance)),
                fits.Column(name="SIMPLE FLUX", format="D", unit="Electrons/group", array=simple_spectrum),
                fits.Column(name="BKD", format="D", unit="Electrons/group", array=bkd)
            ]))

            if i == 20: #int(len(hdul["SCI"].data)/2):
                z_scores_filename = "zscores_{}_" + filename[:-4] + "png"
                plt.clf()
                plt.figure(0, figsize=(18,3))
                plt.imshow(z_scores, vmin=-5, vmax=5, aspect='auto')
                plt.savefig(z_scores_filename.format(i))
                #plt.show()

                spectra_filename = "optspectra_{}_" + filename[:-4] + "png"
                N = hdul[0].header["NGROUPS"] - 1 - BAD_GRPS
                plt.clf()
                plt.plot(spectrum * N, label="Spectra")
                plt.plot(variance * N**2, label="Variance")
                plt.savefig(spectra_filename.format(i))


        output_hdul = fits.HDUList(hdulist)    
        output_hdul.writeto("optx1d_" + os.path.basename(filename), overwrite=True)

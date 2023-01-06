from astropy.io import fits
import astropy.stats
import sys
import matplotlib
#matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from numpy.polynomial.chebyshev import chebval
import scipy.linalg
import os.path
import pdb
from multiprocessing import Pool
from constants import HIGH_ERROR, LEFT_MARGIN, EXTRACT_Y_MIN, EXTRACT_Y_MAX, SUM_EXTRACT_WINDOW, SLITLESS_TOP, SLITLESS_BOT, BAD_GRPS, WCS_FILE, BKD_WIDTH
from scipy.stats import median_abs_deviation


def fix_outliers(data, badpix):
    final = np.copy(data)
    for c in range(LEFT_MARGIN, data.shape[1]):
        rows = np.arange(data.shape[0])
        good = ~badpix[:,c]
        if np.sum(good) == 0:
            print("WARNING: entire col {} is bad, replacing by adjacent cols".format(c))
            final[:,c] = (data[:,c-1] + data[:,c+1])/2
            continue           
                        
        repaired = np.interp(rows, rows[good], data[:,c][good])
        final[:,c] = repaired
    return final

def simple_extract(image, err):
    spectrum = np.sum(image, axis=1)
    variance = np.sum(err**2, axis=1)
    fractions = np.sum(image, axis=0) / np.sum(spectrum)
    return spectrum, variance
    
def get_wavelengths():
    with fits.open(WCS_FILE) as hdul:
        all_ys = np.arange(SLITLESS_TOP, SLITLESS_BOT)
        wavelengths = np.interp(all_ys,
                                (hdul[0].header["IMYSLTL"] + hdul[1].data["Y_CENTER"] - 1)[::-1],
                                hdul[1].data["WAVELENGTH"][::-1])
        return wavelengths
                                
def process_one(filename):
    print("Processing", filename)
    with fits.open(filename) as hdul:
        wavelengths = get_wavelengths()
        hdulist = [hdul[0], hdul["INT_TIMES"]]
    
        for i in range(len(hdul["SCI"].data)):
            print("Processing integration", i)
            
            data = hdul["SCI"].data[i][EXTRACT_Y_MIN:EXTRACT_Y_MAX]
            err = hdul["ERR"].data[i][EXTRACT_Y_MIN:EXTRACT_Y_MAX]
            data[:, 0:LEFT_MARGIN] = 0

            bkd_cols = np.hstack([data[:,LEFT_MARGIN:LEFT_MARGIN+BKD_WIDTH], data[:,-BKD_WIDTH-LEFT_MARGIN:-LEFT_MARGIN]])
            bkd_cols = astropy.stats.sigma_clip(bkd_cols, axis=1)            
            bkd_err_cols = np.hstack([err[:,LEFT_MARGIN:LEFT_MARGIN+BKD_WIDTH], err[:,-BKD_WIDTH-LEFT_MARGIN:-LEFT_MARGIN]])
            
            bkd = np.ma.mean(bkd_cols, axis=1)
            bkd_var = np.sum(bkd_err_cols**2, axis=1) / bkd_err_cols.shape[1]**2
        
            profile = np.sum(data, axis=0)
            trace_loc = np.argmax(profile)
            s = np.s_[EXTRACT_Y_MIN:EXTRACT_Y_MAX, trace_loc - SUM_EXTRACT_WINDOW : trace_loc + SUM_EXTRACT_WINDOW + 1]
        
            spectrum, variance = simple_extract(
                hdul["SCI"].data[i][s] - bkd[:, np.newaxis],
                hdul["ERR"].data[i][s]            
            )
            variance += bkd_var * (2*SUM_EXTRACT_WINDOW + 1)**2
        
            hdulist.append(fits.BinTableHDU.from_columns([
                fits.Column(name="WAVELENGTH", format="D", unit="um", array=wavelengths[EXTRACT_Y_MIN:EXTRACT_Y_MAX]),
                fits.Column(name="FLUX", format="D", unit="Electrons/group", array=spectrum),
                fits.Column(name="ERROR", format="D", unit="Electrons/group", array=np.sqrt(variance)),
                fits.Column(name="BKD", format="D", unit="Electrons/group", array=bkd)
            ]))

            if i == 20:            
                spectra_filename = "spectra_{}_" + filename[:-4] + "png"
                N = hdul[0].header["NGROUPS"] - 1 - BAD_GRPS
                plt.clf()
                plt.plot(spectrum * N, label="Spectra")
                plt.plot(variance * N**2, label="Variance")
                plt.savefig(spectra_filename.format(i))
    
        output_hdul = fits.HDUList(hdulist)
        output_hdul.writeto("x1d_" + os.path.basename(filename), overwrite=True)
    
filenames = sys.argv[1:]
with Pool() as pool:
    pool.map(process_one, filenames)
    

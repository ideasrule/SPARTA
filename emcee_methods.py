import batman
import numpy as np
import emcee
import matplotlib.pyplot as plt
from astropy.stats import sigma_clip
from algorithms import bin_data
import copy
import traceback
import george
from george import kernels
import pandas as pd
import os
import errno
import os.path

def get_batman_params(t0, per, rp, a, inc, limb_dark_coeffs, \
                      t_secondary=None, w=0, ecc=0):
    params = batman.TransitParams()  # object to store transit parameters
    params.t0 = t0  # time of inferior conjunction
    params.per = per  # orbital period
    params.rp = rp  # planet radius (in units of stellar radii)
    params.a = a  # semi-major axis (in units of stellar radii)
    params.inc = inc  # orbital inclination (in degrees)
    params.ecc = ecc  # eccentricity
    params.w = w  # longitude of periastron (in degrees)
    params.limb_dark = "nonlinear"  # limb darkening model
    params.u = limb_dark_coeffs
    params.fp = 1 #we want eclipse to have no planet light

    if t_secondary is None:
        params.t_secondary = params.t0 + params.per / 2
    else:
        params.t_secondary = t_secondary

    return params

def get_planet_flux(eclipse_model, batman_params, t0, period, bjds, Fp, C1, D1,
                    C2=None, D2=None, t_secondary=None, pdb=False):
    if t_secondary is None:
        t_secondary = t0 + period/2.0
        
    w = 2*np.pi/period
    #if planet_sine is None:
    #    planet_sine = np.sin(w*bjds)
    #if planet_cosine is None:
    #    planet_cosine = np.cos(w*bjds)

    planet_sine = np.sin(w*(bjds - t_secondary))
    planet_cosine = np.cos(w*(bjds - t_secondary))

    #planet_sine = np.sin(w*bjds)
    #planet_cosine = np.cos(w*bjds)
    
    Lplanet = Fp + C1*planet_cosine + D1*planet_sine - C1
    
    if C2 is not None:        
        planet_cosine2 = np.cos(2*w*(bjds - t_secondary))
        Lplanet += C2*planet_cosine2 - C2
        assert(False)
        #print("C2")
    if D2 is not None:
        planet_sine2 = np.sin(2*w*(bjds - t_secondary))
        Lplanet += D2*planet_sine2
        assert(False)
        #print("D2")
        
    Lplanet *= (eclipse_model.light_curve(batman_params) - 1)
    #plt.plot(eclipse_model.light_curve(batman_params) - 1)
    #plt.show()
    
    if pdb:
        import pdb
        pdb.set_trace()
    return Lplanet


def plot_fit_and_residuals(phases, binsize, Lobserved, Lexpected, star_variation, gp=None, bjds=None):
    if gp is not None:
        Lexpected += gp.predict(Lobserved-Lexpected, bjds, return_cov=False)
    residuals = Lobserved - Lexpected
    
    f, axarr = plt.subplots(2, sharex=True)
    #f.tight_layout()
    fontsize = 10
    plt.xlabel("Orbital phase", fontsize=fontsize)
    #plt.xlim(-0.6, 0.6)
    
    '''#axarr[0].set_ylim([0.997, 1.001])
    #axarr[0].set_ylim([0.985, 1.006])
    axarr[0].scatter(bin_data(phases,binsize), bin_data(Lobserved - star_variation, binsize), s=10, c='blue', edgecolors='black')
    axarr[0].plot(bin_data(phases,binsize), bin_data(Lexpected - star_variation,binsize), color="r")
    axarr[0].ticklabel_format(useOffset=False)
    axarr[0].set_ylabel("Relative flux", fontsize=fontsize)'''

    #axarr[1].set_ylim([0.9996, 1.0008])
    #axarr[1].set_ylim([0.998, 1.006])
    axarr[0].scatter(bin_data(phases,binsize), bin_data(Lobserved - star_variation, binsize), s=10, c='blue', edgecolors='black')
    axarr[0].plot(bin_data(phases,binsize), bin_data(Lexpected - star_variation,binsize), color="r")
    axarr[0].set_ylabel("Relative flux", fontsize=fontsize)
    axarr[0].ticklabel_format(useOffset=False)
    axarr[0].set_ylim([0.9985, 1.0015])

    #axarr[2].set_ylim([-0.0005, 0.0005])
    #axarr[2].set_ylim([-0.002, 0.002])
    axarr[1].scatter(bin_data(phases,binsize), bin_data(residuals,binsize), s=10, c='blue', edgecolors='black')
    axarr[1].set_ylabel("Relative flux", fontsize=fontsize)
    
def lnprob_transit(params, initial_batman_params, transit_model, bjds,
                           fluxes, errors, initial_t0, plot_result=False,
                           return_residuals=False):    
    transit_offset = params[0]
    rp = params[1]
    a_star = params[2]
    b = params[3]

    a_star = 7.61
    inc = np.arccos(b/a_star) * 180/np.pi
    #inc = 85.5
    
    error_factor = params[4]
    slope = params[5]
    Fstar = params[6]
    A = params[7]
    tau = params[8]
    A2 = params[9]
    tau2 = params[10]

    #print(transit_offset, rp, a_star, b, error_factor, slope, Fstar)
    batman_params = initial_batman_params
    batman_params.t0 = initial_t0 + transit_offset
    batman_params.rp = rp
    batman_params.a = a_star
    batman_params.inc = inc
    
    #now account for prior
    #import pdb
    #pdb.set_trace()
    if (np.abs(params[0])) >= batman_params.per/4.0:
        return -np.inf
    if tau <= 0 or tau2 <= 0: return -np.inf
        
    if error_factor <= 0 or error_factor >= 5: return -np.inf
    if rp <= 0 or rp >= 1 or a_star <= 0 or b <= 0 or b >= 1: return -np.inf
    scaled_errors = error_factor * errors

    delta_t = bjds - bjds[0]
    Lstar = (1 + slope*(bjds-bjds[0]) + A*np.exp(-delta_t/tau) + A2*np.exp(-delta_t/tau2))*transit_model.light_curve(batman_params)
    Lexpected = Fstar * Lstar
    Lobserved = fluxes
    
    residuals = Lexpected - Lobserved
    result = -0.5*(np.sum(residuals**2/scaled_errors**2 - np.log(1.0/scaled_errors**2)))

    if plot_result:
        star_variation = slope*(bjds-bjds[0])*transit_model.light_curve(batman_params) + A*np.exp(-delta_t/tau) + A2*np.exp(-delta_t/tau2)
        binsize = 2
        #residuals -= np.mean(residuals)
        phases = (bjds-batman_params.t0)/batman_params.per
        phases -= np.round(np.median(phases))

        plot_fit_and_residuals(phases, binsize, Lobserved, Lexpected, star_variation)
        plt.figure()
        plt.plot(bjds, transit_model.light_curve(batman_params))


        print(np.std(residuals[phases < -0.09]), np.std(residuals[phases > -0.09]))
        #import pdb
        #pdb.set_trace()
        
    if np.random.randint(0, 1000) == 0:
        print(result/len(residuals), error_factor, np.median(np.abs(residuals)), rp, a_star, inc, b)

    if return_residuals:
        return residuals    

    if np.isnan(result):
        import pdb
        pdb.set_trace()
    return result

def lnprob_transit_limited(params, initial_batman_params, transit_model, bjds,
                           fluxes, errors, initial_t0, plot_result=False,
                           return_residuals=False):
    #if params[0] < 0:
    #    return -np.inf
    
    rp = np.sign(params[0]) * np.sqrt(np.abs(params[0]))
    error_factor = params[1]
    slope = params[2]
    Fstar = params[3]

    batman_params = initial_batman_params
    batman_params.rp = rp

    if error_factor <= 0 or error_factor >= 5: return -np.inf
    #if rp >= 1: return -np.inf
    scaled_errors = error_factor * errors

    delta_t = bjds - bjds[0]
    Lstar = (1 + slope*(bjds-bjds[0]))*transit_model.light_curve(batman_params)
    Lexpected = Fstar * Lstar
    Lobserved = fluxes

    phases = (bjds-batman_params.t0)/batman_params.per
    phases -= np.round(np.median(phases))
    residuals = Lexpected - Lobserved
    #scaled_errors[np.logical_and(phases > 0.01051, phases < 0.01241)] = 1
    #scaled_errors[np.logical_and(phases > 0.0071, phases < 0.0128)] = 1
    
    result = -0.5*(np.sum(residuals**2/scaled_errors**2 - np.log(1.0/scaled_errors**2)))

    if plot_result:
        star_variation = slope*(bjds-bjds[0])*transit_model.light_curve(batman_params)
        binsize = 4
        phases = (bjds-batman_params.t0)/batman_params.per
        phases -= np.round(np.median(phases))

        plot_fit_and_residuals(phases, binsize, Lobserved, Lexpected, star_variation)
        plt.figure()
        plt.plot(bjds, transit_model.light_curve(batman_params))

        
    if np.random.randint(0, 1000) == 0:
        print(result/len(residuals), error_factor, 1e6*rp**2, np.median(np.abs(residuals)))

    if return_residuals:
        return residuals    

    if np.isnan(result):
        import pdb
        pdb.set_trace()
    return result

#@profile    
def lnprob(params, initial_batman_params, transit_model, eclipse_model, bjds,
                           fluxes, errors, y, initial_t0, extra_phase_terms=False, plot_result=False, max_Fp=1,
                           return_residuals=False):
    
    #planet_sine and planet_cosine are sin(w*bjds) and cos(w*bjds); included so we don't have to compute them every iteration
    transit_offset = params[0]
    eclipse_offset = params[1]
    Fp = params[2]
    C1 = params[3]
    D1 = params[4]
    if extra_phase_terms:
        C2 = params[5]
        D2 = params[6]
        end_phase_terms = 7
    else:
        end_phase_terms = 5
    rp = params[end_phase_terms]
    a_star = params[end_phase_terms + 1]
    b = params[end_phase_terms + 2]
    inc = np.arccos(b/a_star) * 180/np.pi
    
    error_factor = params[end_phase_terms + 3]
    slope = 0*params[end_phase_terms + 4]
    Fstar = params[end_phase_terms + 5]
    A = params[end_phase_terms + 6]
    tau = params[end_phase_terms + 7]
    y_coeff = params[end_phase_terms + 8]
    
    fluxes = np.copy(fluxes)
    #fluxes[bjds < 59781.42] += step
    #print("Num step", np.sum(bjds < 59781.42))

    #Fix some parameters
    #a_star = 4.447
    #inc = 79.397
    #b = 0.818248
    #slope = 0
    #a_star = 4.447
    #b = 0.8523
    #inc = 78.95
    #transit_offset = 0
    #eclipse_offset = 1.25147706e-03
    #transit_offset = 0.00012
    #eclipse_offset = 0.0012

    #rp = 0.17296
    #b = 0.826
    #inc = 79.5
    
    batman_params = initial_batman_params
    batman_params.t0 = initial_t0 + transit_offset
    batman_params.t_secondary = initial_t0 + batman_params.per/2.0 + eclipse_offset
    batman_params.rp = rp
    batman_params.a = a_star
    batman_params.inc = inc
    
    #now account for prior
    if (np.abs(params[0])) >= batman_params.per/4.0:
        return -np.inf
        
    if (np.abs(params[1])) >= batman_params.per/4.0:
        return -np.inf
    
    if Fstar <= 0:
        return - np.inf
    
    if tau <= 0 or tau > 0.5:
        return -np.inf

    #print(b)
    if Fp >= max_Fp: return -np.inf
    if error_factor <= 0 or error_factor >= 5: return -np.inf
    if rp <= 0 or rp >= 1 or a_star <= 0 or b <= 0 or b >= 1: return -np.inf
    scaled_errors = error_factor * errors

    delta_t = bjds - bjds[0]
    Lstar = (1 + slope*(bjds-bjds[0]) + A*np.exp(-delta_t/tau) + y_coeff*y)*transit_model.light_curve(batman_params)
    if extra_phase_terms:
        Lplanet = get_planet_flux(eclipse_model, batman_params, batman_params.t0, batman_params.per, bjds, Fp, C1, D1, C2, D2, t_secondary=batman_params.t_secondary)
    else:
        Lplanet = get_planet_flux(eclipse_model, batman_params, batman_params.t0, batman_params.per, bjds, Fp, C1, D1, t_secondary=batman_params.t_secondary)

    if np.min(Lplanet) < 0: return -np.inf
    Lexpected = Fstar * (Lstar + Lplanet)
    Lobserved = fluxes
    
    residuals = Lexpected - Lobserved
    result = -0.5*(np.sum(residuals**2/scaled_errors**2 - np.log(1.0/scaled_errors**2)))

    if plot_result:
        print("lnprob of plotted", result)
        star_variation = Lstar - transit_model.light_curve(batman_params)
        binsize = 1
        #residuals -= np.mean(residuals)
        phases = (bjds-batman_params.t0)/batman_params.per
        phases -= np.round(np.median(phases))

        plot_fit_and_residuals(phases, binsize, Lobserved, Lexpected, star_variation)
        plt.figure()
        plt.scatter(bjds, Lplanet)

        plt.figure()
        plt.scatter(bjds, Lstar)


        print("STD including & excluding near-transit:", np.std(residuals), np.std(residuals[np.abs(phases) > 0.1]))
              
    if np.random.randint(0, 1000) == 0:
        print(result/len(residuals), error_factor, Fp, np.median(np.abs(residuals)), rp, a_star, inc, b)
    #if result/len(residuals) > 4.7:
    #    Lplanet = get_planet_flux(eclipse_model, batman_params, batman_params.t0, batman_params.per, bjds, Fp, C1, D1, t_secondary=batman_params.t_secondary, pdb=True)
        
    #print(result/len(residuals), Fp, np.median(np.abs(residuals)), rp, a_star, inc, b)
    if return_residuals:
        return residuals    

    if np.isnan(result):
        print("result")
    return result

def lnprob_limited(params, batman_params, transit_model, eclipse_model, bjds,
                           fluxes, errors, y, initial_t0, extra_phase_terms=False, plot_result=False, max_Fp=1,
                           return_residuals=False, wavelength=None, output_filename="lightcurves.txt"):
    batman_params = copy.deepcopy(batman_params)
    Fp = params[0]
    C1 = params[1]
    D1 = params[2]
    if extra_phase_terms:
        C2 = params[3]
        D2 = params[4]
        end_phase_terms = 5
    else:
        end_phase_terms = 3
    rp = params[end_phase_terms]
    error_factor = params[end_phase_terms + 1]
    slope = 0*params[end_phase_terms + 2]
    Fstar = params[end_phase_terms + 3]
    A = params[end_phase_terms + 4]
    tau = params[end_phase_terms + 5]
    y_coeff = params[end_phase_terms + 6]
          
    if Fstar <= 0:
        return -np.inf

    if Fp >= max_Fp: return -np.inf
    if error_factor <= 0: return -np.inf
    if rp <= 0 or rp >= 1: return -np.inf
    if tau <= 0 or tau > 0.3: return -np.inf
    #if tau <= 0: return -np.inf



    batman_params.rp = rp
    delta_t = bjds - bjds[0]
    Lstar = (1 + slope*delta_t + A*np.exp(-delta_t/tau) + y_coeff * y)*transit_model.light_curve(batman_params)
    if extra_phase_terms:
        print("Using extra phase terms")
        Lplanet = get_planet_flux(eclipse_model, batman_params, batman_params.t0, batman_params.per, bjds, Fp, C1, D1, C2, D2, t_secondary=batman_params.t_secondary)
    else:
        Lplanet = get_planet_flux(eclipse_model, batman_params, batman_params.t0, batman_params.per, bjds, Fp, C1, D1, t_secondary=batman_params.t_secondary)

    if np.min(Lplanet) < 0: return -np.inf
    Lexpected = Fstar * (Lstar + Lplanet)
    Lobserved = fluxes
    
    residuals = Lexpected - Lobserved
    scaled_errors = errors * error_factor

    phases = (bjds-batman_params.t0)/batman_params.per
    phases -= np.round(np.median(phases))
    #scaled_errors[np.abs(phases) < 0.10] = 10
    result = -0.5*(np.sum(residuals**2/scaled_errors**2 - np.log(1.0/scaled_errors**2)))
    
    if plot_result:
        print("lnprob", result)
        if not os.path.exists(output_filename):
             with open(output_filename, "w") as f:
                 f.write("#wavelength time flux uncertainty model residuals\n")
        
        with open(output_filename, "a") as f:
            for i in range(len(residuals)):
                f.write("{} {} {} {} {} {}\n".format(wavelength, bjds[i], Lobserved[i] / Fstar, scaled_errors[i] / Fstar, Lexpected[i] / Fstar, residuals[i] / Fstar))
            
        binsize = 1
        star_variation = Lstar - transit_model.light_curve(batman_params)
        #residuals -= np.mean(residuals)
        phases = (bjds-batman_params.t0)/batman_params.per
        phases -= np.round(np.median(phases))

        plot_fit_and_residuals(phases, binsize, Lobserved, Lexpected, star_variation)
    
        plt.figure()
        plt.scatter(bjds, Lplanet)
        plt.title("Lplanet")

        plt.figure()
        plt.scatter(bjds, Lstar)
        plt.title("Lstar")


        print(np.std(residuals[phases < -0.09]), np.std(residuals[phases > -0.09]))
    if np.random.randint(0, 1000) == 0:
        print(result/len(residuals), np.median(scaled_errors), error_factor, Fstar, Fp, np.median(np.abs(residuals)), rp)
    #if result/len(residuals) > 4.7:
    #    Lplanet = get_planet_flux(eclipse_model, batman_params, batman_params.t0, batman_params.per, bjds, Fp, C1, D1, t_secondary=batman_params.t_secondary, pdb=True)
        
    #print(result/len(residuals), Fp, np.median(np.abs(residuals)), rp, a_star, inc, b)
    if return_residuals:
        return residuals    

    if np.isnan(result):
        import pdb
        pdb.set_trace()
        print("result")
    return result


def get_initial_positions(initial_params, lnprob, lnprob_args, nwalkers):
    initial_params = np.array(initial_params)
    ndim = len(initial_params)

    positions = []
    for i in range(nwalkers):
        curr_lnprob = -np.inf
        curr_pos = None
        while np.isinf(curr_lnprob):
            curr_pos = initial_params + 1e-2*np.random.randn(ndim) + 1e-2*np.random.randn(ndim)*initial_params
            #curr_pos[7] = initial_params[7] + 0.5*np.random.rand()*initial_params[7]
            #curr_pos[5] = initial_params[5] + 0.5*np.random.rand()*initial_params[5]
            curr_lnprob = lnprob(curr_pos, *lnprob_args)
        positions.append(curr_pos)

    lnprobs = np.array([lnprob(p, *lnprob_args) for p in positions])
    assert(np.sum(np.isinf(lnprobs)) == 0)
    return positions

def run_sampler_return_best(sampler, total_runs, output_dir, output_prefix, init_positions, chunk_size=5000):
    try:
        os.makedirs(output_dir)
    except OSError as exception:
        if exception.errno != errno.EEXIST:
            raise
        
    run_counter = 0
    chunk_counter = 0
    positions = init_positions
    best_lnprob = -np.inf
    best_step = None
    
    while run_counter < total_runs:
        sampler.reset()
        runs_in_chunk = min(total_runs - run_counter, chunk_size)        
        for i, (positions, lnp, _) in enumerate(sampler.sample(positions, iterations=runs_in_chunk)):
            run_counter += 1
            if (run_counter + 1) % 10 == 0:
                print("Progress: {0}/{1}".format(run_counter + 1, total_runs))
        
        if np.max(sampler.flatlnprobability) > best_lnprob:
            index = np.argmax(sampler.flatlnprobability)
            best_lnprob = sampler.flatlnprobability[index]
            best_step = sampler.flatchain[index]
            
        chain_name = os.path.join(output_dir, output_prefix + str(chunk_counter) + "_chain.npy")
        lnprob_name = os.path.join(output_dir, output_prefix + str(chunk_counter) + "_lnprob.npy")
        np.save(chain_name, sampler.flatchain)
        np.save(lnprob_name, sampler.flatlnprobability)
        print("Burn in acceptance fraction for chunk {0}: {1}".format(chunk_counter, np.median(sampler.acceptance_fraction)))
        chunk_counter += 1
        
    return best_step

def run_emcee(lnprob, lnprob_args, initial_params, nwalkers, output_dir, burn_in_runs, production_runs):
    ndim = len(initial_params)
    positions = get_initial_positions(initial_params, lnprob, lnprob_args, nwalkers)

    sampler = emcee.EnsembleSampler(nwalkers, ndim, lnprob,
                                    args=lnprob_args)
    print("Starting burn-in run")
    best_step = run_sampler_return_best(sampler, burn_in_runs, output_dir, "burnin", positions)
    
    latest_positions = [best_step + 1e-4*np.random.randn(ndim)*best_step
                        for i in range(nwalkers)]    
    sampler.reset() #Should already be reset, but be safe
    print("Resetting...")
    print("Starting production run")

    best_step = run_sampler_return_best(sampler, production_runs, output_dir, "production", latest_positions)
    return best_step, sampler.flatchain
    

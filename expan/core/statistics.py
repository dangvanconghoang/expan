import warnings
import logging

import numpy as np
import pandas as pd
from scipy import stats
from expan.core.results import BaseTestStatistics, SampleStatistics, SimpleTestStatistics

logger = logging.getLogger(__name__)


def _delta_mean(x, y):
    """ Calculate the delta of the two groups. Implemented as function to allow being called from bootstrap. """
    return np.nanmean(x) - np.nanmean(y)


def make_delta(assume_normal=True, alpha=0.05, min_observations=20, nruns=10000, relative=False):
    """ A closure to the delta function. """
    return lambda x, y, x_denominators=1, y_denominators=1: delta(x, y, x_denominators, y_denominators, assume_normal, alpha, min_observations, nruns, relative)


def delta(x, y, x_denominators=1, y_denominators=1, assume_normal=True, alpha=0.05, min_observations=20, nruns=10000, relative=False):
    """ Calculates the difference of means between the samples in a statistical sense.
    Computation is done in form of treatment minus control, i.e. x-y.
    Note that NaNs are treated as if they do not exist in the data. 
    
    :param x: sample of the treatment group
    :type  x: pd.Series or array-like
    :param y: sample of the control group
    :type  y: pd.Series or array-like
    :param x_denominators: sample of the treatment group
    :type  x_denominators: pd.Series or array-like
    :param y_denominators: sample of the control group
    :type  y_denominators: pd.Series or array-like
    :param assume_normal: specifies whether normal distribution assumptions can be made
    :type  assume_normal: boolean
    :param alpha: significance level (alpha)
    :type  alpha: float
    :param min_observations: minimum number of observations needed
    :type  min_observations: int
    :param nruns: only used if assume normal is false
    :type  nruns: int
    :param relative: if relative==True, then the values will be returned
            as distances below and above the mean, respectively, rather than the
            absolute values. In	this case, the interval is mean-ret_val[0] to
            mean+ret_val[1]. This is more useful in many situations because it
            corresponds with the sem() and std() functions.
    :type: relative: boolean
    
    :return: results of type SimpleTestStatistics
    :rtype: SimpleTestStatistics
    """
    # Check if data was provided and it has correct format
    if x is None or y is None:
        raise ValueError('Please provide two non-None samples.')
    if not isinstance(x, pd.Series) and not isinstance(x, np.ndarray) and not isinstance(x, list):
        raise TypeError('Please provide samples of type Series or list.')
    if type(x) != type(y):
        raise TypeError('Please provide samples of the same type.')

    # check x and y are 'array-like'
    assert hasattr(x, '__len__')
    assert hasattr(y, '__len__')

    # if *_denominators are not array-like (e.g. int or float), then make them so
    if not hasattr(x_denominators, '__len__'): x_denominators = (x*0.0)+x_denominators
    if not hasattr(y_denominators, '__len__'): y_denominators = (y*0.0)+y_denominators
    assert hasattr(x_denominators, '__len__')
    assert hasattr(y_denominators, '__len__')

    # lengths should match
    assert len(x) == len(x_denominators)
    assert len(y) == len(y_denominators)

    percentiles = [alpha * 100 / 2, 100 - alpha * 100 / 2]

    # Coercing missing values to right format
    _x = np.array(x, dtype=float)
    _y = np.array(y, dtype=float)
    _x_denominators = np.array(x_denominators, dtype=float)
    _y_denominators = np.array(y_denominators, dtype=float)
    _x_ratio = _x / _x_denominators
    _y_ratio = _y / _y_denominators
    _x_strange = _x / np.nanmean(_x_denominators)
    _y_strange = _y / np.nanmean(_y_denominators)

    x_nan = np.isnan(_x_ratio).sum()
    y_nan = np.isnan(_y_ratio).sum()
    if x_nan > 0:
        warnings.warn('Discarding ' + str(x_nan) + ' NaN(s) in the x array!')
        logger.warning('Discarding ' + str(x_nan) + ' NaN(s) in the x array!')
    if y_nan > 0:
        warnings.warn('Discarding ' + str(y_nan) + ' NaN(s) in the y array!')
        logger.warning('Discarding ' + str(x_nan) + ' NaN(s) in the x array!')

    ss_x = sample_size(_x_ratio)
    ss_y = sample_size(_y_ratio)

    # Checking if enough observations are left after dropping NaNs
    lots_of_info = None
    if min(ss_x, ss_y) < min_observations:
        # Set mean to nan
        mu = np.nan
        # Create nan dictionary
        c_i = dict(list(zip(percentiles, np.empty(len(percentiles)) * np.nan)))
    else:
        # Computing the mean
        mu = _delta_mean(_x, _y)
        # Computing the confidence intervals
        if assume_normal:
            logger.info("The distribution of two samples is assumed normal. "
                        "Performing the sample difference distribution calculation.")
            lots_of_info = normal_sample_weighted_difference(x_numerators=_x, y_numerators=_y, x_denominators=_x_denominators, y_denominators = _y_denominators, percentiles=percentiles, relative=relative)
            c_i = lots_of_info['c_i']
            mu = lots_of_info['mean1'] - lots_of_info['mean2']
        else:
            logger.info("The distribution of two samples is not normal. Performing the bootstrap.")
            c_i, _ = bootstrap(x=_x_strange, y=_y_strange, percentiles=percentiles, nruns=nruns, relative=relative)

    if lots_of_info is not None: # correct the last few lines!!
        treatment_statistics = SampleStatistics(ss_x, lots_of_info['mean1'], lots_of_info['var1'])
        control_statistics   = SampleStatistics(ss_y, lots_of_info['mean2'], lots_of_info['var2'])
    else:
        # actually, this is a bit rubbish, only applies to bootstrap and min_observations:
        treatment_statistics = SampleStatistics(ss_x, float(np.nanmean(_x_strange)), float(np.nanvar(_x_strange)))
        control_statistics   = SampleStatistics(ss_y, float(np.nanmean(_y_strange)), float(np.nanvar(_y_strange)))

    variant_statistics   = BaseTestStatistics(control_statistics, treatment_statistics)
    if lots_of_info is not None:
        p_value              = lots_of_info['p_value']
    else:
        p_value              = compute_p_value_from_samples(_x_strange, _y_strange)
    statistical_power    = compute_statistical_power_from_samples(_x_strange, _y_strange, alpha) # TODO: wrong


    logger.info("Delta calculation finished!")
    return SimpleTestStatistics(variant_statistics.control_statistics,
                                variant_statistics.treatment_statistics,
                                float(mu), c_i, p_value, statistical_power)


def sample_size(x):
    """ Calculates valid sample size given the data.

    :param x: sample to calculate the sample size
    :type  x: pd.Series or list (array-like)

    :return: sample size of the sample excluding nans
    :rtype: int
    """
    # cast into a dummy numpy array to infer the dtype
    x_as_array = np.array(x)

    if np.issubdtype(x_as_array.dtype, np.number):
        _x = np.array(x, dtype=float)
        x_nan = np.isnan(_x).sum()
    # assuming categorical sample
    elif isinstance(x, pd.core.series.Series):
        x_nan = x.str.contains('NA').sum()
    else:
        x_nan = list(x).count('NA')

    return int(len(x) - x_nan)


def estimate_sample_size(x, mde, r, alpha=0.05, beta=0.2):
    """
    Estimates sample size based on sample mean and variance given MDE (Minimum Detectable effect), 
    number of variants and variant split ratio
    
    :param x: sample to base estimation on
    :type  x: pd.Series or pd.DataFrame
    :param mde: minimum detectable effect
    :type  mde: float
    :param r: variant split ratio
    :type  r: float
    :param alpha: significance level
    :type  alpha: float
    :param beta: type II error
    :type  beta: float
    
    :return: estimated sample size
    :rtype: float or pd.Series
    """
    if not isinstance(x, pd.Series) and not isinstance(x, pd.DataFrame):
        raise TypeError("Sample x needs to be either Series or DataFrame.")

    if r <= 0:
        raise ValueError("Variant split ratio needs to be higher than 0.")

    ppf = stats.norm.ppf
    c1 = (ppf(1.0 - alpha/2.0) - ppf(beta))**2
    c2 = (1.0 + r) * c1 * (1.0 + 1.0 / r)
    return c2 * x.var() / (mde * x.mean())**2


def bootstrap(x, y, func=_delta_mean, nruns=10000, percentiles=[2.5, 97.5],
              min_observations=20, return_bootstraps=False, relative=False):
    """ Bootstraps the Confidence Intervals for a particular function comparing two samples. 
    NaNs are ignored (discarded before calculation).

    :param x: sample of the treatment group
    :type  x: pd.Series or list (array-like)
    :param y: sample of the control group
    :type  y: pd.Series or list (array-like)
    :param func: function of which the distribution is to be computed.
                 The default comparison metric is the difference of means. 
                 For bootstraping correlation: func=lambda x,y: np.stats.pearsonr(x,y)[0].
    :type  func: function
    :param nruns: number of bootstrap runs to perform
    :type  nruns: int
    :param percentiles: The values corresponding to the given percentiles are returned. 
                        The default percentiles (2.5% and 97.5%) correspond to an alpha of 0.05.
    :type  percentiles: list
    :param min_observations: minimum number of observations necessary
    :type  min_observations: int
    :param return_bootstraps: If this variable is set the bootstrap sets are returned,
                              otherwise the first return value is empty.
    :type  return_bootstraps: bool
    :param relative: if relative==True, then the values will be returned as distances below and above the mean, 
                     respectively, rather than the absolute values. 
                     In this case, the interval is mean-ret_val[0] to mean+ret_val[1]. 
                     This is more useful in many situations because it corresponds with the sem() and std() functions.
    :type  relative: bool
    
    :return (c_val, bootstraps): c_val is a dict which contains percentile levels (index) and values
                                 bootstraps is a np.array containing the bootstrapping results per run
    :rtype: tuple
    """
    # Checking if data was provided
    if x is None or y is None:
        raise ValueError('Please provide two non-None samples.')

    # Transform data to appropriate format
    _x = np.array(x, dtype=float)
    _y = np.array(y, dtype=float)
    ss_x = _x.size - np.isnan(_x).sum()
    ss_y = _y.size - np.isnan(_y).sum()

    # Checking if enough observations are left after dropping NaNs
    if min(ss_x, ss_y) < min_observations:
        # Create nan percentile dictionary
        c_val = dict(list(zip(percentiles, np.empty(len(percentiles)) * np.nan)))
        return (c_val, None)
    else:
        # Initializing bootstraps array and random sampling for each run
        bootstraps = np.ones(nruns) * np.nan
        for run in range(nruns):
            # Randomly choose values from _x and _y with replacement
            xp = _x[np.random.randint(0, len(_x), size=(len(_x),))]
            yp = _y[np.random.randint(0, len(_y), size=(len(_y),))]
            # Application of the given function to the bootstraps
            bootstraps[run] = func(xp, yp)
        # If relative is set subtract mean from bootstraps
        if relative:
            bootstraps -= np.nanmean(bootstraps)
        # Confidence values per given percentile as dictionary
        c_val = dict(list(zip(percentiles, np.percentile(bootstraps, q=percentiles))))
        return (c_val, None) if not return_bootstraps else (c_val, bootstraps)


def pooled_std(std1, n1, std2, n2):
    """ Returns the pooled estimate of standard deviation. 

    For further information visit:
        http://sphweb.bumc.bu.edu/otlt/MPH-Modules/BS/BS704_Confidence_Intervals/BS704_Confidence_Intervals5.html

    :param std1: standard deviation of first sample
    :type  std1: float
    :param n1: size of first sample
    :type  n1: int
    :param std2: standard deviation of second sample
    :type  std2: float
    :param n2: size of second sample
    :type  n2: int

    :return: pooled standard deviation
    :type: float
    """
    if std1 != std2 and not (0.5 < (std1 ** 2) / (std2 ** 2) < 2.):
        warnings.warn('Sample variances differ too much to assume that population variances are equal.')
        logger.warning('Sample variances differ too much to assume that population variances are equal.')

    return np.sqrt(((n1 - 1) * std1 ** 2 + (n2 - 1) * std2 ** 2) / (n1 + n2 - 2))


def normal_sample_difference(x, y, percentiles=[2.5, 97.5], relative=False):
    """ Calculates the difference distribution of two normal distributions given by their samples.

    Computation is done in form of treatment minus control.
    It is assumed that the standard deviations of both distributions do not differ too much.

    :param x: sample of a treatment group
    :type  x: pd.Series or list (array-like)
    :param y: sample of a control group
    :type  x: pd.Series or list (array-like)
    :param percentiles: list of percentile values to compute
    :type  percentiles: list
    :param relative: If relative==True, then the values will be returned
                     as distances below and above the mean, respectively, rather than the
                     absolute values. In this case, the interval is mean-ret_val[0] to
                     mean+ret_val[1]. This is more useful in many situations because it
                     corresponds with the sem() and std() functions.
    :type relative: bool
    
    :return: percentiles and corresponding values
    :rtype: dict
    """
    # Coerce data to right format
    _x = np.array(x, dtype=float)
    _x = _x[~np.isnan(_x)]
    _y = np.array(y, dtype=float)
    _y = _y[~np.isnan(_y)]

    # Calculate statistics
    mean1 = np.mean(_x)
    mean2 = np.mean(_y)
    std1 = np.std(_x)
    std2 = np.std(_y)
    n1 = len(_x)
    n2 = len(_y)

    # Push calculation to normal difference function
    return normal_difference(mean1=mean1, std1=std1, n1=n1,
                             mean2=mean2, std2=std2, n2=n2,
                             percentiles=percentiles, relative=relative)

def normal_sample_weighted_difference(x_numerators, y_numerators, x_denominators, y_denominators, percentiles=[2.5, 97.5], relative=False):
    """ Calculates the difference distribution of two normal distributions given by their samples.

    Computation is done in form of treatment minus control.
    It is assumed that the standard deviations of both distributions do not differ too much.

    :param x: sample of a treatment group
    :type  x: pd.Series or list (array-like)
    :param y: sample of a control group
    :type  x: pd.Series or list (array-like)
    :param percentiles: list of percentile values to compute
    :type  percentiles: list
    :param relative: If relative==True, then the values will be returned
                     as distances below and above the mean, respectively, rather than the
                     absolute values. In this case, the interval is mean-ret_val[0] to
                     mean+ret_val[1]. This is more useful in many situations because it
                     corresponds with the sem() and std() functions.
    :type relative: bool

    :return: percentiles and corresponding values
    :rtype: dict with multiple entries:
                confidence_interval
                mean1
                mean2
                n1
                n2
                var1
                var2
    """

    assert isinstance(x_numerators, np.ndarray)
    assert isinstance(x_denominators, np.ndarray)
    assert isinstance(y_numerators, np.ndarray)
    assert isinstance(y_denominators, np.ndarray)
    assert x_numerators.dtype == 'float'
    assert x_denominators.dtype == 'float'
    assert y_numerators.dtype == 'float'
    assert y_denominators.dtype == 'float'

    # perform the ratio
    _x_ratio = x_numerators / x_denominators
    _y_ratio = y_numerators / y_denominators

    # find the nans (including 0/0)
    x_nans = np.isnan(_x_ratio)
    y_nans = np.isnan(_y_ratio)

    # remove the nans
    _x_ratio = _x_ratio[~x_nans]
    _y_ratio = _y_ratio[~y_nans]
    x_numerators = x_numerators[~x_nans]
    y_numerators = y_numerators[~y_nans]
    x_denominators = x_denominators[~x_nans]
    y_denominators = y_denominators[~y_nans]

    # check they're all the same length
    assert 1 == len(set( map(len, [_x_ratio,x_numerators,x_denominators])))
    assert 1 == len(set( map(len, [_y_ratio,y_numerators,y_denominators])))

    # Calculate statistics
    mean1 = np.mean(x_numerators) / np.mean(x_denominators)
    mean2 = np.mean(y_numerators) / np.mean(y_denominators)
    errors_1 = x_numerators - (x_denominators * mean1)
    errors_2 = y_numerators - (y_denominators * mean2)
    std1 = np.std(errors_1 / np.mean(x_denominators))
    std2 = np.std(errors_2 / np.mean(y_denominators))
    n1 = len(_x_ratio)
    n2 = len(_y_ratio)

    #print('\n',mean1-mean2,'\n')

    # Push calculation to normal difference function
    c_i = normal_difference(mean1=mean1, std1=std1, n1=n1,
                             mean2=mean2, std2=std2, n2=n2,
                             percentiles=percentiles, relative=relative)
    p_value = compute_p_value(mean1, std1, n1, mean2, std2, n2)
    return  {   'c_i':  c_i
            ,   'mean1': mean1
            ,   'mean2': mean2
            ,   'n1': n1
            ,   'n2': n2
            ,   'var1': np.var(errors_1 / np.mean(x_denominators))
            ,   'var2': np.var(errors_2 / np.mean(y_denominators))
            ,   'p_value': p_value
            }


def normal_difference(mean1, std1, n1, mean2, std2, n2, percentiles=[2.5, 97.5], relative=False):
    """ Calculates the difference distribution of two normal distributions.
    Computation is done in form of treatment minus control. It is assumed that
    the standard deviations of both distributions do not differ too much.

    For further information visit:
        http://sphweb.bumc.bu.edu/otlt/MPH-Modules/BS/BS704_Confidence_Intervals/BS704_Confidence_Intervals5.html

    :param mean1: mean value of the treatment distribution
    :type  mean1: float
    :param std1: standard deviation of the treatment distribution
    :type  std1: float
    :param n1: number of samples of the treatment distribution
    :type  n1: int
    :param mean2: mean value of the control distribution
    :type  mean2: float
    :param std2: standard deviation of the control distribution
    :type  std2: float
    :param n2: number of samples of the control distribution
    :type  n2: int
    :param percentiles: list of percentile values to compute
    :type  percentiles: list
    :param relative: If relative==True, then the values will be returned
                     as distances below and above the mean, respectively, rather than the
                     absolute values. In this case, the interval is mean-ret_val[0] to
                     mean+ret_val[1]. This is more useful in many situations because it
                     corresponds with the sem() and std() functions.
    :type relative: bool
    
    :return: percentiles and corresponding values
    :rtype: dict
    """
    # Compute combined parameters from individual parameters
    mean = mean1 - mean2
    std = pooled_std(std1, n1, std2, n2)
    # Computing standard error
    st_error = std * np.sqrt(1. / n1 + 1. / n2)
    # Computing degrees of freedom
    d_free = n1 + n2 - 2

    # Mapping percentiles via standard error
    if relative:
        return dict([(round(p, 5), stats.t.ppf(p / 100.0, df=d_free) * st_error) for p in percentiles])
    else:
        return dict([(round(p, 5), mean + stats.t.ppf(p / 100.0, df=d_free) * st_error) for p in percentiles])


def compute_statistical_power_from_samples(x, y, alpha=0.05):
    """ Compute statistical power given data samples of control and treatment.

    :param x: samples of a treatment group
    :type  x: pd.Series or array-like
    :param y: samples of a control group
    :type  y: pd.Series or array-like
    :param alpha: Type I error (false positive rate)
    :type  alpha: float
    
    :return: statistical power---the probability of a test to detect an effect if the effect actually exists
    :rtype: float
    """
    z_1_minus_alpha = stats.norm.ppf(1 - alpha/2.)
    _x = np.array(x, dtype=float)
    _x = _x[~np.isnan(_x)]
    _y = np.array(y, dtype=float)
    _y = _y[~np.isnan(_y)]

    mean1 = np.mean(_x)
    mean2 = np.mean(_y)
    std1 = np.std(_x)
    std2 = np.std(_y)
    n1 = len(_x)
    n2 = len(_y)
    return compute_statistical_power(mean1, std1, n1, mean2, std2, n2, z_1_minus_alpha)


def compute_statistical_power(mean1, std1, n1, mean2, std2, n2, z_1_minus_alpha):
    """ Compute statistical power given statistics of control and treatment.
    
    :param mean1: mean value of the treatment distribution
    :type  mean1: float
    :param std1: standard deviation of the treatment distribution
    :type  std1: float
    :param n1: number of samples of the treatment distribution
    :type  n1: int
    :param mean2: mean value of the control distribution
    :type  mean2: float
    :param std2: standard deviation of the control distribution
    :type  std2: float
    :param n2: number of samples of the control distribution
    :type  n2: int
    :param z_1_minus_alpha: critical value for significance level alpha. That is, z-value for 1-alpha.
    :type  z_1_minus_alpha: float
    
    :return: statistical power---the probability of a test to detect an effect if the effect actually exists 
                                    or -1 if std is less or equal to 0
    :rtype: float
    """
    effect_size = mean1 - mean2
    std = pooled_std(std1, n1, std2, n2)
    if std <= 0.0:
        logger.error("Zero pooled std in compute_statistical_power.")
        return -1

    tmp = (n1 * n2 * effect_size**2) / ((n1 + n2) * std**2)
    z_beta = z_1_minus_alpha - np.sqrt(tmp)
    beta = stats.norm.cdf(z_beta)
    power = 1 - beta
    return power


def compute_p_value_from_samples(x, y):
    """ Calculates two-tailed p value for statistical Student's T-test based on pooled standard deviation.

    :param x: samples of a treatment group
    :type  x: pd.Series or array-like
    :param y: samples of a control group
    :type  y: pd.Series or array-like

    :return: two-tailed p-value 
    :rtype: float
    """
    if x is None or y is None:
        raise ValueError('Please provide two non-empty samples to compute p-values.')

    _x = np.array(x, dtype=float)
    _x = _x[~np.isnan(_x)]
    _y = np.array(y, dtype=float)
    _y = _y[~np.isnan(_y)]

    mean1 = np.mean(_x)
    mean2 = np.mean(_y)
    std1 = np.std(_x)
    std2 = np.std(_y)
    n1 = len(_x)
    n2 = len(_y)
    return compute_p_value(mean1, std1, n1, mean2, std2, n2)


def compute_p_value(mean1, std1, n1, mean2, std2, n2):
    """ Compute two-tailed p value for statistical Student's T-test given statistics of control and treatment.
    
    :param mean1: mean value of the treatment distribution
    :type  mean1: float
    :param std1: standard deviation of the treatment distribution
    :type  std1: float
    :param n1: number of samples of the treatment distribution
    :type  n1: int
    :param mean2: mean value of the control distribution
    :type  mean2: float
    :param std2: standard deviation of the control distribution
    :type  std2: float
    :param n2: number of samples of the control distribution
    :type  n2: int
    
    :return: two-tailed p-value 
    :rtype: float
    """
    mean_diff = mean1 - mean2
    std       = pooled_std(std1, n1, std2, n2)
    st_error  = std * np.sqrt(1. / n1 + 1. / n2)
    d_free    = n1 + n2 - 2
    if st_error == 0.0:
        t         = np.sign(mean_diff) * 1000
    else:
        t         = mean_diff / st_error
    p         = stats.t.cdf(-abs(t), df=d_free) * 2
    return p

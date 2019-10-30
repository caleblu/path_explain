import warnings
import numpy as np
from tqdm import tqdm

class MarginalExplainer(object):
    '''
    A class for computing the conditional expectation of a function
    (model) given knowledge of certain features
    '''
    
    def __init__(self, model, data, nsamples, feature_dependence='independent', representation='mobius'):
        '''
        Initializes the class object.
        
        Args:
            model: A function or callable that can be called on input data to produce output.
            data:  A numpy array of input data to sample background references from.
                   Typically this represents the same matrix the model was trained on.
            nsamples: The number of samples to draw from the data when computing the expectation.
            feature_dependence: One of `independent`, `dependent`. This parameter
                                controls how the explainer samples background samples.
                                In the former case, it simply draws from the data uniformly at random.
                                In the latter case, it draws samples using the (approximate)
                                conditional distribution.
            representation: One of `mobius`, `comobius`, or `average`. Using `mobius`,
                            the main effects are represented as E[f|x_i]. Using `comobius`,
                            they are E[f|X_{N\i}]. Using `average` averages the two cases.
        '''
        self.model    = model
        self.data     = data
        self.nsamples = nsamples
        self.feature_dependence = feature_dependence
        self.representation     = representation
        
        if len(self.data) < self.nsamples:
            raise ValueError('Requested more samples than amount of background data provided!')
        
        if self.feature_dependence not in ['independent', 'dependent']:
            raise ValueError('''Unrecognized value `{}` for argument feature_dependence. 
            Must be one of `independent`, `dependent`.'''.format(self.feature_dependence))
        
        if self.feature_dependence == 'dependent':
            warnings.warn('You have specified dependent feature sampling. Note that this ' + \
                          'is current performed by sorting the data for every sample and ' + \
                          'every feature, which is quite slow.')
        
        if self.representation not in ['mobius', 'comobius', 'average']:
            raise ValueError('''Unrecognized value `{}` for argument representation. 
            Must be one of `mobius`, `comobius`, `average`.'''.format(self.representation))
    
    def _sample_background(self, number_to_draw, target_example, feature_index):
        '''
        An internal function to sample data from a background distribution.
        
        Args:
            number_to_draw: The number of samples to draw.
            target_example: The current example x.
            feature_index: Which feature (or set of features) represent the
                           target set.
        Returns:
            A data matrix of number_to_draw samples sampled from the background distribution.
        '''
        if self.feature_dependence == 'independent':
            sample_indices = np.random.choice(self.nsamples, number_to_draw, replace=False)
            return self.data[sample_indices]
        else:
            #Right now the way I'm doing this is by sorting examples with respect to their
            #feature-wise difference to the target feature. This is slow and should be improved,
            #but it was easy to code so here we are.
            abs_diff_from_feature = np.abs(target_example[feature_index] - sample_indices[:, feature_index])
            abs_diff_ranking      = np.argsort(abs_diff_from_feature)[::-1]
            return self.data[abs_diff_from_ranking[number_to_draw]]

    def _construct_sample_vector(self, target_example, background_samples, feature_index):
        '''
        An internal function to compute the vector x_S or x_{N\S}, or both.
        
        Args:
            target_example: The current example x.
            background_samples: A set of input vectors that represent
                                the background distribution.
            feature_index: Which feature (or set of features) represent the
                           target set
        
        Returns:
            The target vector x_S or x_{N\S}, or in the case of 
            `average`, a tuple containing (x_S, x_{N\S}).
        '''
        mobius_vector = background_samples.copy()
        mobius_vector[:, feature_index] = target_example[feature_index]

        comobius_vector = target_example.copy()
        comobius_vector = np.expand_dims(comobius_vector, axis=0)
        comobius_vector = np.tile(comobius_vector, (background_samples.shape[0], 1))
        comobius_vector[:, feature_index] = background_samples[:, feature_index]
            
        if self.representation == 'mobius':
            return mobius_vector
        elif self.representation == 'comobius':
            return comobius_vector
        else:
            return (mobius_vector, comobius_vector)
    
    def explain(self, X, feature_indices=None, batch_size=50, verbose=False):
        '''
        Computes the main effects of the model on data X. 
        
        Args:
            X: A data matrix. The samples you want to compute
               the main effects for.
            feature_indices: The indices of features whose main effects
                             you want to compute. Defaults to all features.
            batch_size: The batch size to use while calling the model.
            verbose:    Whether or not to log progress while doing computation.
            
        Returns:
            A matrix of shape [num_samples, len(feature_indices)]. The main effects
            of each feature.
        '''
        if feature_indices is None:
            feature_indices = np.arange(X.shape[-1])
        
        main_effects = np.zeros((X.shape[0], len(feature_indices)))
        
        data_iterable = enumerate(X)
        if verbose:
            data_iterable = enumerate(tqdm(X))
        
        for j, target_example in data_iterable:
            for k, feature_index in enumerate(feature_indices):
                for i in range(0, self.nsamples, batch_size):
                    number_to_draw     = min(self.nsamples, i + batch_size) - i
                    background_samples = self._sample_background(number_to_draw, target_example, feature_index)
                    sample_vector      = self._construct_sample_vector(target_example, background_samples, feature_index)
                    
                    if self.representation == 'mobius':
                        difference    = np.sum(self.model(sample_vector)) - np.sum(self.model(background_samples))
                    elif self.representation == 'comobius':
                        #I've hacked a quick solution here: multiply the baseline v(N) by the number of samples
                        #drawn for v(N\{i}). This technically works to put them on the same magnitude,
                        #but is numerically unstable. It would be better to actually perform the mean
                        #calculations over the sampling and keep v(N) as a stable quantity.
                        difference    = number_to_draw * np.sum(self.model(np.expand_dims(target_example, axis=0))) - \
                                        np.sum(self.model(sample_vector))
                    else:
                        mobius_diff   = np.sum(self.model(sample_vector[0])) - np.sum(self.model(background_samples))
                        comobius_diff = number_to_draw * np.sum(self.model(np.expand_dims(target_example, axis=0))) - \
                                        np.sum(self.model(sample_vector[1]))
                        difference    = (mobius_diff + comobius_diff) * 0.5
                    
                    main_effects[j, k] += difference
        
        main_effects /= self.nsamples
        return main_effects

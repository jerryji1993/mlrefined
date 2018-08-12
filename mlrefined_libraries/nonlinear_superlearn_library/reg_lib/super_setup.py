import autograd.numpy as np
from . import super_optimizers 
from . import super_cost_functions
from . import normalizers
from . import multilayer_perceptron
from . import multilayer_perceptron_batch_normalized
from . import polys
from . import fourier

from . import history_plotters

class Setup:
    def __init__(self,x,y,**kwargs):
        # link in data
        self.x = x
        self.y = y
        
        # make containers for all histories
        self.weight_histories = []
        self.train_cost_histories = []
        self.train_count_histories = []
        self.valid_cost_histories = []
        self.valid_count_histories = []
        self.train_costs = []
        self.train_counts = []
        self.valid_costs = []
        self.valid_counts = []
        
    #### define preprocessing steps ####
    def preprocessing_steps(self,**kwargs):        
        ### produce / use data normalizer ###
        name = 'standard'
        if 'name' in kwargs:
            name = kwargs['name']
        self.normalizer_name = name

        # produce normalizer / inverse normalizer
        s = normalizers.Setup(self.x,name)
        self.normalizer = s.normalizer
        self.inverse_normalizer = s.inverse_normalizer
        
        # normalize input 
        self.x = self.normalizer(self.x)
       
    #### split data into training and validation sets ####
    def make_train_val_split(self,train_portion):
        # translate desired training portion into exact indecies
        self.train_portion = train_portion
        r = np.random.permutation(self.x.shape[1])
        train_num = int(np.round(train_portion*len(r)))
        self.train_inds = r[:train_num]
        self.valid_inds = r[train_num:]
        
        # define training and testing sets
        self.x_train = self.x[:,self.train_inds]
        self.x_valid = self.x[:,self.valid_inds]
        
        self.y_train = self.y[:,self.train_inds]
        self.y_valid = self.y[:,self.valid_inds]
     
    #### define cost function ####
    def choose_cost(self,name,**kwargs):
        # create training and testing cost functions
        self.cost_object = super_cost_functions.Setup(name,**kwargs)

        # if the cost function is a two-class classifier, build a counter too
        if name == 'softmax' or name == 'perceptron':
            self.count_object = super_cost_functions.Setup('twoclass_counter',**kwargs)
                        
        if name == 'multiclass_softmax' or name == 'multiclass_perceptron':
            self.count_object = super_cost_functions.Setup('multiclass_counter',**kwargs)
  
        self.cost_name = name
    
    #### define feature transformation ####
    def choose_features(self,**kwargs): 
        ### select from pre-made feature transforms ###
        layer_sizes = [1]
        if 'layer_sizes' in kwargs:
            layer_sizes = kwargs['layer_sizes']
        
        # add input and output layer sizes
        input_size = self.x.shape[0]
        layer_sizes.insert(0, input_size)
      
        # add output size
        if self.cost_name == 'least_squares' or self.cost_name == 'least_absolute_deviations':
            layer_sizes.append(self.y.shape[0])
        else:
            num_labels = len(np.unique(self.y))
            if num_labels == 2:
                layer_sizes.append(1)
            else:
                layer_sizes.append(num_labels)
        
        # multilayer perceptron #
        name = 'multilayer_perceptron'
        if 'name' in kwargs:
            name = kwargs['name']
           
        if name == 'multilayer_perceptron':
            transformer = multilayer_perceptron.Setup(**kwargs)
            self.feature_transforms = transformer.standard_feature_transforms
            self.initializer = transformer.standard_initializer
            if 'activation' in kwargs:
                if kwargs['activation'] == 'maxout':
                    self.feature_transforms = transformer.maxout_feature_transforms
                    self.initializer = transformer.maxout_initializer                   
            self.layer_sizes = transformer.layer_sizes
            
        if name == 'multilayer_perceptron_batch_normalized':
            transformer = multilayer_perceptron_batch_normalized.Setup(**kwargs)
            self.feature_transforms = transformer.feature_transforms
            self.initializer = transformer.initializer
            if 'activation' in kwargs:
                if kwargs['activation'] == 'maxout':
                    self.feature_transforms = transformer.maxout_feature_transforms
                    self.initializer = transformer.maxout_initializer    
            self.layer_sizes = transformer.layer_sizes
            
        # polynomials #
        if name == 'polys':
            self.transformer = polys.Setup(self.x,self.y,**kwargs)
            self.feature_transforms = self.transformer.feature_transforms
            self.initializer = self.transformer.initializer
            self.degs = self.transformer.D
            
        # cos
        if name == 'fourier':
            self.transformer = fourier.Setup(self.x,self.y,**kwargs)
            self.feature_transforms = self.transformer.feature_transforms
            self.initializer = self.transformer.initializer
            self.degs = self.transformer.D
            
        self.feat_name = name
        
        ### with feature transformation constructed, pass on to cost function ###
        self.cost_object.define_feature_transform(self.feature_transforms)
        self.cost = self.cost_object.cost
        self.model = self.cost_object.model
        
        # if classification performed, inject feature transforms into counter as well
        if self.cost_name == 'softmax' or self.cost_name == 'perceptron' or self.cost_name == 'multiclass_softmax' or self.cost_name == 'multiclass_perceptron':
            self.count_object.define_feature_transform(self.feature_transforms)
            self.counter = self.count_object.cost
            
    #### run optimization ####
    def fit(self,**kwargs):
        # basic parameters for gradient descent run (default algorithm)
        self.max_its = 500; self.alpha_choice = 10**(-1); self.lam = 0;
        self.algo = 'gradient_descent'
        if 'algo' in kwargs:
            self.algo = kwargs['algo']
            
        # set parameters by hand
        if 'max_its' in kwargs:
            self.max_its = kwargs['max_its']
        if 'alpha_choice' in kwargs:
            self.alpha_choice = kwargs['alpha_choice']
        if 'lam' in kwargs:
            self.lam = kwargs['lam']
            
        # set initialization
        self.w_init = self.initializer()
        if 'w' in kwargs:
            self.w_init = kwargs['w']
        
        # batch size for gradient descent?
        self.train_num = np.size(self.y_train)
        self.valid_num = np.size(self.y_valid)
        self.batch_size = np.size(self.y_train)
        if 'batch_size' in kwargs:
            self.batch_size = min(kwargs['batch_size'],self.batch_size)
        
        # verbose or not
        verbose = True
        if 'verbose' in kwargs:
            verbose = kwargs['verbose']

        # optimize
        weight_history = []
        cost_history = []
        
        # set numericxal stability parameter / regularization parameter
        lam = 10**(-7)
        if 'lam' in kwargs:
            lam = kwargs['lam']
                
        # run gradient descent
        if self.algo == 'gradient_descent':
            weight_history,train_cost_history,valid_cost_history = super_optimizers.gradient_descent(self.cost,self.w_init,self.x_train,self.y_train,self.x_valid,self.y_valid,self.alpha_choice,self.max_its,self.batch_size,verbose,lam)
            
            
        if self.algo == 'newtons_method':                
            weight_history,train_cost_history,valid_cost_history = super_optimizers.newtons_method(self.cost,self.w_init,self.x_train,self.y_train,self.x_valid,self.y_valid,self.alpha_choice,self.max_its,self.batch_size,verbose,lam)
                                                                                         
        # store all new histories
        self.weight_histories.append(weight_history)
        self.train_cost_histories.append(train_cost_history)
        self.valid_cost_histories.append(valid_cost_history)

        # if classification produce count history
        if self.cost_name == 'softmax' or self.cost_name == 'perceptron' or self.cost_name == 'multiclass_softmax' or self.cost_name == 'multiclass_perceptron':
            train_count_history = [self.counter(v,self.x_train,self.y_train) for v in weight_history]
            valid_count_history = [self.counter(v,self.x_valid,self.y_valid) for v in weight_history]

            # store count history
            self.train_count_histories.append(train_count_history)
            self.valid_count_histories.append(valid_count_history)
 
    #### plot histories ###
    def show_histories(self,**kwargs):
        start = 0
        if 'start' in kwargs:
            start = kwargs['start']
        if self.train_portion == 1:
            self.valid_cost_histories = [[] for s in range(len(self.valid_cost_histories))]
            self.valid_count_histories = [[] for s in range(len(self.valid_count_histories))]
        history_plotters.Setup(self.train_cost_histories,self.train_count_histories,self.valid_cost_histories,self.valid_count_histories,start)
        
    #### for batch normalized multilayer architecture only - set normalizers to desired settings ####
    def fix_normalizers(self,w):
        ### re-set feature transformation ###        
        # fix normalization at each layer by passing data and specific weight through network
        self.feature_transforms(self.x,w);
        
        # re-assign feature transformation based on these settings
        self.testing_feature_transforms = self.transformer.testing_feature_transforms
        
        ### re-assign cost function (and counter) based on fixed architecture ###
        funcs = cost_functions.Setup(self.cost_name,self.x,self.y,self.testing_feature_transforms)
        self.model = funcs.model
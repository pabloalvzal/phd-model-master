from SALib.sample import morris as mos
from SALib.analyze import morris as moa
from SALib.test_functions import Ishigami
import numpy as np


# Source
# http://salib.readthedocs.io/en/latest/basics.html

# Define the model inputs
problem = {
    'num_vars': 3,
    'names': ['x1', 'x2', 'x3'],
    'bounds': [[-3.14159265359, 3.14159265359],
               [-3.14159265359, 3.14159265359],
               [-3.14159265359, 3.14159265359]]
}

problem_alt = {
    'num_vars': 17,
    'names': ['thsat0', 'thsat1', 'thsat2',
              'thfc0', 'thfc1', 'thfc2',
              'thwp0', 'thwp1', 'thwp2',
              'gamma0', 'gamma1',
              's0', 's1',
              'clf0', 'clf1', 'clf2',
              'cadr1'
              ],
    'bounds': [[0.01, 0.61], [0.01, 0.61], [0.01, 0.61],  # sat
               [0.01, 0.40], [0.01, 0.40], [0.01, 0.40],  # fc
               [0.01, 0.10], [0.01, 0.10], [0.01, 0.10],  # wp
               [0.001, 1], [0.001, 1],  # gamma
               [0.004852, 1], [0.004852, 1],  # s
               [0.001, 1], [0.001, 1], [0.001, 1],  # clf
               [0.001, 1]  # cadr
               ]
}

# Generate samples
# Store in a 8000-samples by 3-variables numpy matrix

"""
p-level grid (i.e quartiles = 4 groups, centiles = 10 groups, etc.)
num_levels (int)-> The number of grid levels

'p' is the number of possible levels that
    the input parameter x_i can take.

'p' is recommended to be even, and typically = 4.

Delta
'delta' is a value in {1/(p-1), 2/(p-1),..., 1-1/(p-1)}

    But it is advised that delta = 1/(2*(p-1)
"""

"""
Dairon...
p is the number of level in the grid (gamma) for each dimension. 
Values of p = 4 and r = 10 are generally satisfactory for screening factor.
"""
p = 4.0  # q in Dairon
delta = p/(2*(p-1))
r = 10  # Trajectories
param_values = mos.sample(problem_alt, r, num_levels=p, grid_jump=delta)
print(param_values.shape)  # -> (4000, 3)
print(param_values.shape[0])  # -> 4000
vector = param_values[0]
print (vector[0])
print(param_values[0])
# print(param_values[0][0])
# print(param_values)
# Run model (example)
Y = Ishigami.evaluate(param_values)

Si = moa.analyze(problem, param_values, Y, num_resamples=1000, print_to_console=True,
                 grid_jump=delta, num_levels=p)


"""
Si - A dictionary of sensitivity indices containing the following entries.

mu - the mean elementary effect
mu_star - the absolute of the mean elementary effect
sigma - the standard deviation of the elementary effect
mu_star_conf - the bootstrapped confidence interval
names - the names of the parameters

"""
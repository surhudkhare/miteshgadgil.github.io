# Name: Mitesh Gadgil
# Email: mgadgil@ucsd.edu
# PID: A53095
from pyspark import SparkContext
sc = SparkContext()

### Definition of some global parameters.
K = 5  # Number of centroids
RUNS = 25  # Number of K-means runs that are executed in parallel. Equivalently, number of sets of initial points
RANDOM_SEED = 60295531
converge_dist = 0.1 # The K-means algorithm is terminated when the change in the location 
                    # of the centroids is smaller than 0.1

					
import numpy as np
import pickle
import sys
from numpy.linalg import norm
from matplotlib import pyplot as plt

def print_log(s):
    sys.stdout.write(s + "\n")
    sys.stdout.flush()


def parse_data(row):
    '''
    Parse each pandas row into a tuple of (station_name, feature_vec),
    where feature_vec is the concatenation of the projection vectors
    of TAVG, TRANGE, and SNWD.
    '''
    return (row[0],
            np.concatenate([row[1], row[2], row[3]]))


def compute_entropy(d):
    '''
    Compute the entropy given the frequency vector `d`
    '''
    d = np.array(d)
    d = 1.0 * d / d.sum()
    return -np.sum(d * np.log2(d))


def choice(p):
    '''
    Generates a random sample from [0, len(p)),
    where p[i] is the probability associated with i. 
    '''
    random = np.random.random()
    r = 0.0
    for idx in range(len(p)):
        r = r + p[idx]
        if r > random:
            return idx
    assert(False)


def kmeans_init(rdd, K, RUNS, seed):
    '''
    Select `RUNS` sets of initial points for `K`-means++
    '''
    # the `centers` variable is what we want to return
    n_data = rdd.count()
    shape = rdd.take(1)[0][1].shape[0]
    centers = np.zeros((RUNS, K, shape))

    def update_dist(vec, dist, k):
        new_dist = norm(vec - centers[:, k], axis=1)**2
        return np.min([dist, new_dist], axis=0)

    data = rdd.map(lambda p: (p, [np.inf] * RUNS)).cache()
    # Collect the feature vectors of all data points beforehand, might be
    # useful in the following for-loop
    local_data = rdd.map(lambda (name, vec): vec).collect()
    sample = [local_data[k] for k in np.random.randint(0, len(local_data), RUNS)]
    centers[:, 0] = sample

    for idx in range(K - 1):      
        data = data.map(lambda (p,d): (p,update_dist(p[1],d,idx))).cache()
        if idx==0:
            pass
        centers[:,idx] = data.flatMap(lambda (p,d): [(i,([p[1]],[d[i]])) for i in range(len(d))])\
						.reduceByKey(lambda x,y: (x[0]+y[0],x[1]+y[1]))\
						.map(lambda (r,v):(r,(v[0],v[1]/sum(v[1]))))\
						.map(lambda (r,v): (r,v[0][choice(v[1])]))\
						.sortByKey()\
						.values().collect()
        return centers


def get_closest(p, centers):
    '''
    Return the indices the nearest centroids of `p`.
    `centers` contains sets of centroids, where `centers[i]` is
    the i-th set of centroids.
    '''
    best = [0] * len(centers)
    closest = [np.inf] * len(centers)
    for idx in range(len(centers)):
        for j in range(len(centers[0])):
            temp_dist = norm(p - centers[idx][j])
            if temp_dist < closest[idx]:
                closest[idx] = temp_dist
                best[idx] = j
    return best


def kmeans(rdd, K, RUNS, converge_dist, seed):
    '''
    Run K-means++ algorithm on `rdd`, where `RUNS` is the number of
    initial sets to use.
    '''
    k_points = kmeans_init(rdd, K, RUNS, seed)
    print_log("Initialized.")
    temp_dist = 1.0

    iters = 0
    st = time.time()
    while temp_dist > converge_dist:
        new_points = rdd.map(lambda p: (p[1],get_closest(p[1],k_points)))\
						.flatMap(lambda (v,j): [((r,j[r]),(v,1)) for r in range(RUNS)])\
						.reduceByKey(lambda x,y: (x[0]+y[0],x[1]+y[1]))\
						.map(lambda (k,v): (k,v[0]/v[1])).collectAsMap()
        temp = new_points[new_points.keys()[0]].shape
        keys_v = [(i,k) for k in range(K) for i in range(RUNS)]
        keys_p = new_points.keys()
        for (idx,j) in set(keys_v)-set(keys_p):
            new_points[(idx,j)] = np.zeros(temp)
        # You can modify this statement as long as `temp_dist` equals to
        # max( sum( l2_norm of the movement of j-th centroid in each centroids set ))
        ##############################################################################

        temp_dist = np.max([
                np.sum([norm(k_points[idx][j] - new_points[(idx, j)]) for j in range(K)])
                    for idx in range(RUNS)])

        iters = iters + 1
        if iters % 5 == 0:
            print_log("Iteration %d max shift: %.2f (time: %.2f)" %
                      (iters, temp_dist, time.time() - st))
            st = time.time()
        
        for ((idx, j), p) in new_points.items():
            k_points[idx][j] = p
               
    return k_points

import pickle
data = pickle.load(open("../Data/Weather/stations_projections.pickle", "rb"))
rdd = sc.parallelize([parse_data(row[1]) for row in data.iterrows()])
rdd.take(1)

# main code

import time

st = time.time()

np.random.seed(RANDOM_SEED)
centroids = kmeans(rdd, K, RUNS, converge_dist, np.random.randint(1000))
group = rdd.mapValues(lambda p: get_closest(p, centroids))            .collect()

print "Time takes to converge:", time.time() - st

def get_cost(rdd, centers):
    '''
    Compute the square of l2 norm from each data point in `rdd`
    to the centroids in `centers`
    '''
    def _get_cost(p, centers):
        best = [0] * len(centers)
        closest = [np.inf] * len(centers)
        for idx in range(len(centers)):
            for j in range(len(centers[0])):
                temp_dist = norm(p - centers[idx][j])
                if temp_dist < closest[idx]:
                    closest[idx] = temp_dist
                    best[idx] = j
        return np.array(closest)**2
    
    cost = rdd.map(lambda (name, v): _get_cost(v, centroids)).collect()
    return np.array(cost).sum(axis=0)

cost = get_cost(rdd, centroids)

log2 = np.log2

log2(np.max(cost)), log2(np.min(cost)), log2(np.mean(cost))

entropy = []

for i in range(RUNS):
    count = {}
    for g, sig in group:
        _s = ','.join(map(str, sig[:(i + 1)]))
        count[_s] = count.get(_s, 0) + 1
    entropy.append(compute_entropy(count.values()))


print 'entropy=',entropy
best = np.argmin(cost)
print 'best_centers=',list(centroids[best])


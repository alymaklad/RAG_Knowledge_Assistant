# Week 6: Bayesian Networks

## Why graphical models

A joint distribution over n binary variables needs 2^n - 1 numbers to specify. For 30 variables that is more than a billion parameters, far too many to store or to learn from data. Probabilistic graphical models avoid this by exploiting conditional independence: most variables interact directly with only a few others.

A Bayesian network is a directed acyclic graph (DAG) in which every node is a random variable and every edge points from a parent to a child. Each node stores a conditional probability table (CPT) that gives the distribution of the node given each combination of its parents' values.

The network represents the joint distribution through the chain rule for Bayesian networks: the joint probability of all variables equals the product, over every node, of the probability of that node given its parents. A network over 30 binary variables where no node has more than three parents needs at most 30 x 8 = 240 numbers.

## The burglary alarm example

The classic example has five variables: Burglary (B), Earthquake (E), Alarm (A), JohnCalls (J) and MaryCalls (M). Burglaries and earthquakes both can set off the alarm. John and Mary are neighbours who call when they hear the alarm, but John sometimes confuses the telephone with the alarm, and Mary often misses the alarm because she listens to loud music.

The edges are B -> A, E -> A, A -> J and A -> M. The CPT for Alarm has four rows, one for each combination of Burglary and Earthquake. For example, P(A = true | B = true, E = false) = 0.94 and P(A = true | B = false, E = false) = 0.001.

---page---

## Conditional independence and d-separation

Every Bayesian network encodes a set of conditional independence assumptions. The local Markov property says that each node is conditionally independent of its non-descendants given its parents.

D-separation is the graphical test for whether two sets of variables are independent given a third set. A path between two nodes is blocked by the evidence if it contains one of three patterns:

1. A chain X -> Z -> Y where the middle node Z is observed.
2. A fork X <- Z -> Y where the common cause Z is observed.
3. A collider X -> Z <- Y where neither Z nor any descendant of Z is observed.

The collider case behaves the opposite way from the other two. Observing a common effect makes its causes dependent. This is called explaining away: if the alarm is ringing and we learn there was an earthquake, the probability of a burglary goes down.

## The Markov blanket

The Markov blanket of a node consists of its parents, its children, and the other parents of its children (its co-parents). Given its Markov blanket, a node is conditionally independent of every other node in the network.

The Markov blanket matters in practice because it is all the information needed to update one variable. Gibbs sampling, for example, resamples each variable from its distribution conditioned only on its Markov blanket, which keeps every step cheap even in a large network.

In the alarm network, the Markov blanket of Alarm is {Burglary, Earthquake, JohnCalls, MaryCalls}. The Markov blanket of Burglary is {Alarm, Earthquake}, because Earthquake is a co-parent of Alarm.

---page---

## Exact inference by variable elimination

Inference means computing a posterior such as P(Burglary | JohnCalls = true, MaryCalls = true). Enumeration sums the full joint distribution over all hidden variables, which is exponential in the number of variables.

Variable elimination avoids repeated work. It writes the query as a sum of products of CPT factors, then sums out the hidden variables one at a time. Each step multiplies only the factors that mention the variable being eliminated and replaces them with a single new factor.

The order in which variables are eliminated changes the cost dramatically. The cost is governed by the size of the largest factor created, which depends on the treewidth of the network under that ordering. Finding the optimal ordering is NP-hard, so practical systems use heuristics such as min-degree or min-fill.

For polytrees (networks with at most one undirected path between any two nodes), exact inference takes time linear in the size of the network. For general networks exact inference is NP-hard, which motivates approximate methods such as likelihood weighting and Gibbs sampling.

## Learning the parameters

When every variable is observed in the training data, the maximum-likelihood estimate of each CPT entry is a simple ratio of counts: the number of examples where the child takes a value and the parents take a given configuration, divided by the number of examples with that parent configuration.

Counts of zero lead to probabilities of zero, which can make the model rule out events that are merely rare. Laplace smoothing fixes this by adding one pseudo-count to every cell of the table before normalizing.

# graphs-theory

Repository for homeworks of the Graphs Theory course.

## Task 1

Performance comparison of the stock LAGraph implementations on CPU and the stock spla implementations on GPU. The algorithms are BFS, SSSP, triangle counting, and PageRank on undirected graphs. The run records timings and profiling.

To reproduce the results, update the submodules recursively and run the shell script from `task1`:

```bash
git submodule update --init --recursive
cd task1
bash run_all_benchmarks.sh
```

## Task 2

Strong scaling analysis of the stock distributed D-Galois implementations (MPI ranks as
single-thread nodes) for BFS, SSSP, triangle counting, and PageRank. The run
records timings, speedup, and sanity checks across node counts 1, 2, 4, and 8.

To reproduce the results, initialize the Galois submodule and run the shell script from `task2`:

```bash
git submodule update --init task2/deps/Galois
cd task2
bash scripts/run.sh
```

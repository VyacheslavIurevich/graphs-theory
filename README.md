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

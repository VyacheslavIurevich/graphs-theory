# Эксперимент 2: масштабируемость D-Galois по числу узлов

Имитация распределённой системы на одном CPU: каждый MPI-ранг — отдельный
узел с одним вычислительным потоком (`-t=1`). Цель — **strong scaling**
алгоритмов BFS, SSSP, TC и PageRank из `lonestar/analytics/distributed`.

Журнал решений и ловушек для нового чата: [`CONTEXT.md`](CONTEXT.md).
Большие графы: [`LARGE_GRAPHS.md`](LARGE_GRAPHS.md).

---

## Прогон на стенде task1 (то, что нужно сделать)

Стенд из `task1/results/README.md`: Intel Core i5-1135G7, 4 ядра / 8 потоков,
**40 ГБ RAM**. На ноутбуке (~8 ГБ) полный набор не гонять.

```bash
# из корня репозитория
git submodule update --init task2/deps/Galois
cd task2
bash scripts/run_stand.sh
```

Долго: сборка + конвертация Orkut/RGG + все алгоритмы на 1,2,4,6 рангах.
Имеет смысл в `tmux`/`screen` или через `nohup`:

```bash
cd task2
nohup bash scripts/run_stand.sh > /tmp/task2-stand.out 2>&1 &
```

Досъём в уже привезённый каталог (не гоняет заново валидные 1/2/4):

```bash
cd task2
TASK2_OUTPUT=results/stand-20260930-174954 TASK2_RESUME=1 \
  nohup bash scripts/run_stand.sh > /tmp/task2-stand-resume.out 2>&1 &
```

Переменные, если нужно сузить прогон:

| Переменная | По умолчанию | Пример |
|---|---|---|
| `TASK2_NODES` | `1,2,4,6` | `1,2,4` — только честные слоты |
| `TASK2_DATASETS` | `all` | `large` или `belgium_osm,com-Orkut` |
| `TASK2_TIMEOUT` | `21600` (6 ч на один процесс) | `7200` |
| `TASK2_OUTPUT` | `results/stand-<UTC>` | `/data/task2-out` |
| `TASK2_RESUME` | авто, если в OUTPUT уже есть `report.json` | `1` принудительно, `0` с нуля |

Эквивалент без shell-обёртки:

```bash
python3 scripts/benchmark.py run --profile stand --dataset all --nodes 1,2,4,6 \
  --output results/stand-20260930-174954 --resume
```

`--profile stand` включает все графы из config, снимает ноутбучный
`max_nodes` и ставит длинный таймаут. TC на орграфах скрипт skip'ает сам.

### Что отдать обратно

Весь каталог, который скрипт напечатает в конце (он же `WHAT_TO_SEND.txt`):

```
task2/results/stand-<timestamp>/
  report.json          # все метрики, команды, sanity
  report.md            # таблица scaling
  stand_info.txt       # CPU / RAM / git rev / список графов
  console.log          # полный stdout
  runs/*.log
  runs/*.stats.csv
```

Без `report.json` + `stand_info.txt` + логов разбор почти бесполезен.
Симлинк `results/recent` указывает на последний запуск — его копировать
не обязательно, он относительный.

Один упавший граф не останавливает остальные: статус `error`/`timeout`
попадёт в JSON, прогон идёт дальше.

---

## Модель «узел = ранг»

| Параметр | Значение | Зачем |
|---|---|---|
| `mpirun --use-hwthread-cpus -n P --bind-to none` | P процессов на localhost | P имитируемых узлов; слоты = гиперпотоки, иначе OpenMPI видит 4 ядра и отказывается стартовать P=6 |
| `-t=1` | один compute-поток на ранг | плюс внутренний communication thread Gluon |
| `GALOIS_DO_NOT_BIND_THREADS=1` | обязательно | иначе Galois биндит потоки и они дерутся с MPI |
| `-partition=oec` | outgoing edge-cut | рекомендация Galois для ≤16 хостов |
| `-exec=Sync` | BSP | одинаковое число раундов на всех P |
| `-runs=4` | 1 warmup + 3 замера | `Timer_0` отбрасывается |

Это **не** shared-memory Galois с `-t=P`.

На стенде 8 потоков: каждый ранг занимает compute+comm, поэтому **P=4
заполняет машину честно**. P=6 — мягкий oversubscribe (12 программных
потоков на 8 аппаратных), точка за честным потолком. P=8 не снимаем:
16 потоков на 8 аппаратных и OpenMPI без `--use-hwthread-cpus` даже не
стартует. См. [`LARGE_GRAPHS.md`](LARGE_GRAPHS.md).

---

## Алгоритмы

Штатные distributed-бинарники, исходники Galois не патчатся.

| Алгоритм | Бинарник | Почему этот вариант |
|---|---|---|
| BFS | `bfs-push-dist` | README Galois: push быстрее pull |
| SSSP | `sssp-push-dist` | то же; веса рёбер = 1, как unweighted SSSP в task1 |
| PageRank | `pagerank-pull-dist` | README: pull быстрее push; ровно 20 итераций |
| TC | `triangle-counting-dist` | единственный DistTC; CPU-ядро есть в `tc.cpp` |

TC только на неориентированных (`-symmetricGraph`). Орграфы не
симметризуются.

---

## Датасеты

Те же SuiteSparse URL, что в `task1/spla-bench`. Локальные архивы ищутся в
`task1/results/graphs-theory-datasets/`.

**Default (уже прогнаны на ноутбуке 8 ГБ):**

| Датасет | Роль |
|---|---|
| `coAuthorsCiteseer` | маленький collaboration; нижняя граница, MPI > работы |
| `amazon-2008` | орграф, исключённый в task1 из-за симметризации spla |
| `belgium_osm` | дорожная сеть большого диаметра, узкий BFS/SSSP |

**Большие (включаются `--profile stand` / `run_stand.sh`):**
`coPapersDBLP`, `roadNet-CA`, `cit-Patents`, `rgg_n_2_22_s0`,
`soc-LiveJournal1`, `com-Orkut`, `rgg_n_2_23_s0`, `road_central`.

Как включить выборочно и что значит `max_nodes` — [`LARGE_GRAPHS.md`](LARGE_GRAPHS.md).
Обоснование каждого графа — `DatasetSpec.why` в `scripts/config.py`.

---

## Метрики

Собирается то, без чего нельзя отличить computation / communication /
imbalance / load.

| Метрика | Откуда | Зачем |
|---|---|---|
| `kernel_ms_median` | `Timer_i`, i≥1, HMAX | время алгоритма без I/O; база scaling |
| `speedup`, `efficiency` | T(1)/T(p), S(p)/p | прямой ответ эксперимента |
| `graph_construct_ms` | `GraphConstructTime` | партиционирование отдельно от kernel |
| `wall_ms` | `time.monotonic` вокруг `mpirun` | end-to-end |
| `num_iterations_median` | `NumIterations_*` | рост раундов = цена разреза |
| `host_imbalance` | `PRINT_PER_HOST_STATS=1` HostValues | max/mean по рангам |
| Gluon bytes/msgs | `GALOIS_COMM_STATS=1` | когда упираемся в коммуникацию |
| sanity | stdout | тот же ответ на любом P |
| `peak_rss_kb` | `/usr/bin/time -v` | память × число рангов |

PageRank: `-maxIterations=20` и недостижимый tolerance, чтобы объём работы
не зависел от P. BFS/SSSP идут до сходимости; число итераций сохраняется.

Формулы: `S(p)=T(1)/T(p)`, `E(p)=S(p)/p`. База — тот же граф, тот же
бинарник, `p=1`.

Не собираются flamegraph, PAPI и GPU.

---

## Сборка и зависимости

```bash
cd task2
python3 scripts/benchmark.py build          # или build --force
python3 scripts/benchmark.py prepare        # только default-графы
python3 scripts/benchmark.py prepare --dataset all
```

Нужны: CMake ≥ 3.13, GCC/Clang C++17, Boost (serialization+iostreams), LLVM
с RTTI, MPI, libnuma. `{fmt}`: если нет системного пакета, `build.py` ставит
10.2.1 в `third_party/fmt`.

Исходники Galois не меняются. Обход GCC 15: `-DCMAKE_CXX_FLAGS=-include cstdint`.

Cursor AppImage выставляет `APPDIR` — CMake тогда ищет модули внутри
AppImage и падает с `Could not find CMAKE_ROOT`. `scripts/util.py` снимает
`APPDIR`/`APPIMAGE` и чистит `LD_LIBRARY_PATH`. `run_stand.sh` делает то же.

OpenMPI `--version` на части машин печатает ошибку help-файлов; `mpirun -n`
при этом работает.

---

## Конвертация

`mtx2gr -edgeType=void` в Galois 6.0 падает. Путь: MTX → 0-based edgelist
(симметричный MTX раскрывается, петли выбрасываются) → `edgelist2gr`.

- BFS/PR: `.gr` void + `.tgr`
- SSSP: `.wgr` uint32 вес 1 + `.wtgr`
- TC: `.cgr` без петель/мультирёбер, копия в `.sgr` (`gr2sgr` нельзя —
  рёбра уже двунаправленные)

Текстовые `.el`/`.wel` после конвертации удаляются, чтобы Orkut не забил диск.

---

## Ноутбук (~8 ГБ), уже снято

Intel Core i5-1235U, 10c/12t. Default-sweep `coAuthorsCiteseer`,
`amazon-2008`, `belgium_osm` на 1,2,4,8 рангах лежит в
`results/20260930-132349/`. Это **не** стенд task1 и не замена полному
прогону: на 8 рангах ноутбук oversubscribe, большие графы не влезают.

```bash
python3 scripts/benchmark.py run --algo bfs --dataset coAuthorsCiteseer --nodes 1,2
```

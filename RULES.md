# Python & PostgreSQL Data Pipeline Optimization Challenge

**Transform massive JSONB datasets into normalized relational structures as fast and reliably as possible.**  
**Host:** Igor Moreira (Community Hackathon)

## Overview
This hackathon challenges participants to optimize a real-world **Python and PostgreSQL data pipeline** that expands large volumes of JSONB records into a relational database structure over SSH.

**Primary goal:** Is to minimize processing time (ultimately targeting datasets of up to **300 million rows**) while preserving mandatory data-validation and versioning safeguards.

**Secondary goal:** Is to introduce reliable **checkpoint and resume capabilities** so interrupted operations can recover without losing progress or leaving inconsistent artifacts.

Solutions will be evaluated not only on execution time, but also on **RAM usage, temporary storage requirements, scalability, and failure resilience**.

## Description
The challenge is based on a real Python application designed to remotely manage PostgreSQL databases running on a Linux server through SSH. The application provides a graphical interface for database administration, table inspection, data processing, and version-controlled database operations.

One of its core features is the **Expand** operation. A source table called `raw_data` stores heterogeneous records inside a PostgreSQL `jsonb` column named `raw`. The expansion pipeline reads these records, validates their origin and destination structures, transforms the JSONB content, and distributes the resulting information across multiple relational tables.

The application and the challenge dataset are available through the official project repository:  
`https://github.com/igorsiecz/kaggle_postgre_challenge`

### The Performance Problem
The current expansion process works correctly, but its execution time becomes increasingly significant as the number of source records grows.

Processing relatively small datasets is manageable. However, when the source table contains millions of rows, a complete expansion may require hours. The long-term objective is to make the architecture capable of efficiently processing datasets containing up to **300 million rows**.

Participants are therefore encouraged to investigate the entire expansion pipeline, identify its main bottlenecks, and redesign or optimize any part of the implementation that limits performance.

Possible approaches may involve Python optimization, PostgreSQL optimization, query redesign, batching strategies, parallel processing, data-transfer reduction, transaction management, COPY-based operations, multiprocessing, improved SQL generation, or entirely different processing architectures.

Participants are free to significantly modify the implementation as long as the required outputs and integrity guarantees are preserved.

### Primary Challenge: Expansion Performance
The primary objective is to minimize the processing time reported by the application's **Expansion Performance Report**.

The main benchmark metric is:  
`MEASURED PROCESSING TOTAL`

The report separates the expansion into multiple processing stages, allowing participants to identify where execution time is being spent and measure the effect of their optimizations.

Performance will ultimately be evaluated by the organizers on a standardized environment using reproducible datasets generated specifically for this competition.

Execution time is the primary metric, but solutions should also remain practical in terms of:
* RAM consumption;
* temporary disk usage;
* database storage overhead;
* scalability with increasing dataset size.

A solution that achieves extremely fast processing by requiring unreasonable memory or temporary storage may therefore be considered less effective than a slightly slower but significantly more scalable implementation.

### Secondary Challenge: Failure Recovery
The current implementation performs an expansion as a continuous operation without persistent checkpoints.

If communication between the Windows DB Manager and the Linux/PostgreSQL server is interrupted, the operation may not be recoverable. Depending on when the interruption occurs, this can result in:
* loss of nearly completed processing;
* incomplete database states;
* an expansion completing without its expected version record;
* temporary or intermediate artifacts remaining in the database;
* the entire operation having to be restarted.

Participants should improve the architecture so that long-running expansions can recover safely from interruptions.

Solutions may implement mechanisms such as persistent checkpoints, resumable processing, automatic recovery, explicit resume controls, transactional state tracking, or other architectures that provide equivalent guarantees.

The objective is not to prescribe one specific implementation, but to ensure that a processing failure does not unnecessarily destroy previously completed work or leave the database in an inconsistent state.

### Non-Negotiable Requirements
Optimization must not be achieved by simply removing operations required for data integrity.

In particular, solutions must preserve the existing functional guarantees associated with:
* source validation;
* destination validation;
* relational output correctness;
* database version registration;
* dump/version handling;
* traceability of completed expansions.

Participants may redesign how these operations are implemented, combine them, parallelize them, cache information, or replace them with more efficient equivalent mechanisms.

They may **not**, however, eliminate the guarantees themselves.

The challenge is therefore not simply to make the code execute fewer operations. It is to design a faster and more resilient data-processing architecture while preserving the behavior required by the application.

## Getting Started
This section describes how to reproduce the original challenge environment and execute the baseline `raw_data` expansion before modifying the code.

Participants should first reproduce the baseline successfully. Only after obtaining a valid **Expansion Performance Report** should optimization work begin.

### 1. Prepare a Linux PostgreSQL Server
The architecture of this challenge intentionally separates the graphical DB Manager from the database server:
* the **DB Manager must run on Windows**;
* **PostgreSQL must run on Linux**;
* the DB Manager administers PostgreSQL through **SSH**.

The Linux environment does not need to be a dedicated physical computer. Suitable options include: a dedicated Linux machine; a Linux virtual machine; Hyper-V; WSL; VMware or VirtualBox; a Linux cloud VM.

The SSH-based architecture must remain available because it is part of the system being optimized and tested.

Install on Linux:
* PostgreSQL;
* an SSH server;
* PostgreSQL command-line tools, including `psql`, `pg_dump`, and `pg_restore`.

### 2. Create a PostgreSQL Role
Use the PostgreSQL `postgres` superuser or create a dedicated PostgreSQL role for the challenge.

The role should be able to log in and create databases:
```pgsql
CREATE ROLE <postgres_user>
    WITH LOGIN CREATEDB
    PASSWORD '<strong_postgres_password>';
```

The same PostgreSQL role should be used by both the database generator and the DB Manager.

For the SSH-tunneled configuration, PostgreSQL may remain bound to localhost. Ensure that the role can authenticate from the Linux loopback interface according to your `pg_hba.conf` configuration.

A typical rule is:
```apache
host    all    <postgres_user>    127.0.0.1/32    scram-sha-256
```

SSH and PostgreSQL are separate services:
* SSH commonly uses port `22`;
* PostgreSQL commonly uses port `5432`.

Do not confuse the two ports.

### 3. Download and Run the DB Manager
The challenge source code is available at:  
`https://github.com/igorsiecz/kaggle_postgre_challenge`

Clone the repository on the Windows computer:
```bash
git clone [https://github.com/igorsiecz/kaggle_postgre_challenge.git](https://github.com/igorsiecz/kaggle_postgre_challenge.git)
cd kaggle_postgre_challenge
```

Install the Python dependencies:
```bash
python -m pip install -r requirements.txt
```
*Python 3.10 or newer is recommended.*

Start the application:
```bash
python main.py
```

### 4. Perform the First Connection
In the upper-left area of the application, select **Connect**. Provide:
* Linux server IP/address;
* SSH port;
* Linux SSH username;
* Linux SSH password or the configured SSH authentication method;
* PostgreSQL port;
* PostgreSQL username created in Step 2;
* PostgreSQL password.

You may enable **Remember credentials** if desired. On Windows, remembered credentials are encrypted locally for the current Windows user rather than stored as plain-text credentials.

On the first successful connection, the application should automatically prepare its control infrastructure, including:
* database `postgres_data_manager`;
* schema `app_control`.

If the automatic setup fails, refer to the repository `README.md` for the manual PostgreSQL setup procedure before continuing.

### 5. Generate the Challenge Database
The repository contains the deterministic database generator: `generate_database.py`

The generator creates a standalone PostgreSQL database named: `kaggle_challenge`

It populates the challenge schema, including the `raw_data` source table and the destination relational tables required for the expansion. All benchmark datasets must be created using this official generator.

**Do not modify the generator or its fixed seed.** Each generated record is deterministic, allowing consistent comparisons as dataset size increases.

#### Generate the initial 100,000-row database
On Windows PowerShell, first provide the PostgreSQL password through the challenge-specific environment variable:
```powershell
$env:PG_KAGGLE_CHALLENGE_PASS = "<strong_postgres_password>"
```

Then run:
```powershell
python generate_database.py `
  --rows 100000 `
  --host <linux_server_ip> `
  --ssh_port <linux_ssh_port> `
  --ssh_user <linux_ssh_user> `
  --postgres_port 5432 `
  --user <postgres_user> `
  --admin_database postgres
```
Replace every value inside `<...>` with the appropriate value for your environment. For more information, read `GENERATE_DATASET_README.md`.

The generator automatically creates an SSH tunnel to PostgreSQL. The SSH password, if required, is requested interactively by OpenSSH and is not passed as a command-line parameter.

The generator intentionally refuses to overwrite an existing `kaggle_challenge` database. To intentionally delete and regenerate the challenge database from scratch, add:
```text
--replace
```

The generator also contains its own checkpoint/resume mechanism for interrupted **database generation**. This is independent of the competition's secondary objective, which is to introduce equivalent failure recovery into the DB Manager's **Expand operation**.

### 6. Open the Generated Database
Start the DB Manager again and reconnect to the Linux server.

Select dataset: `kaggle_challenge`  
Then open table: `raw_data`

The application will display a preview of the generated records. The synthetic data has no real-world meaning and contains no original project data. Its structure and scale are designed to reproduce the relevant processing characteristics of the original application.

### 7. Configure the Baseline Expansion
With `raw_data` open, select the **Expand** button at the top of the table window. The expansion configuration requires:
* **Your name**
* **Version title**

Both fields must contain a value. The values themselves do not affect benchmark performance. They are used to identify the generated version.

### 8. Configure the Six Destination Tables
The competition package provides six SQL files:
```text
01_table3.sql
02_table4.sql
03_table1.sql
04_table5.sql
05_table6.sql
06_table2.sql
```
They must be configured in **exactly this order**.

* **Destination 1:** Select: `public.table3`. Completely replace the SQL Console contents with the contents of: `01_table3.sql`
* **Destination 2:** Click: `+ Destination`. Select: `public.table4`. Replace the SQL Console contents with: `02_table4.sql`
* (Repeat for the rest)

The final configuration must therefore be:

| Order | Destination table | SQL file |
| :--- | :--- | :--- |
| 1 | `public.table3` | `01_table3.sql` |
| 2 | `public.table4` | `02_table4.sql` |
| 3 | `public.table1` | `03_table1.sql` |
| 4 | `public.table5` | `04_table5.sql` |
| 5 | `public.table6` | `05_table6.sql` |
| 6 | `public.table2` | `06_table2.sql` |

Do not change the destination mapping when measuring the official challenge workload.

### 9. Run the Baseline Expansion
After confirming all six destination tabs, click: **Run expansion**

The progress window will display the execution status. For the initial 100,000-row dataset, the operation is intended primarily as a functional test and baseline benchmark. Processing should be much lighter than the larger workloads targeted by the challenge.

When the expansion finishes, the application automatically opens the **Expansion Performance Report**.

The report contains detailed timing information for the individual processing stages. It can be exported as a `.txt` file. The most important value is: `MEASURED PROCESSING TOTAL`. You may record this value before modifying the code. This is the primary processing-time metric used by the competition.

### 10. Begin Optimization
Once the original implementation successfully completes the 100,000-row baseline, participants may begin modifying the code. You are encouraged to investigate the complete processing architecture rather than focusing only on isolated Python functions. Major architectural changes are allowed.

However, optimized implementations must preserve the required outputs and the integrity guarantees defined in the competition rules.

### 11. Test Larger Datasets
After validating an optimization on 100,000 rows, regenerate the challenge database with progressively larger values of `--rows`. Participants may continue with increasingly large datasets according to the capacity of their own hardware. The ultimate engineering objective is to make the expansion architecture capable of efficiently processing datasets containing up to **300 million rows**.

Local benchmark results are valuable for development and should be reported in the final Writeup, but they do not determine the competition ranking. All official performance comparisons will be reproduced by the judging team on the same standardized infrastructure.

## Submission Requirements
A valid final submission must provide enough information and code for the judging team to independently reproduce, benchmark, and test the proposed solution.

The authoritative implementation must be publicly available in a Git repository.

### Required Submission Components
1. **Kaggle Writeup**
2. **Public GitHub Repository**
3. **Exact Submission Commit**

All required components must be available before the competition deadline. **Draft or unsubmitted Kaggle Writeups will not be considered for judging.**

### 1. Kaggle Writeup
The Kaggle Writeup serves as the participant's project report. It should clearly describe:
* the main performance bottlenecks identified in the original implementation;
* the optimization strategy adopted;
* major architectural changes;
* database and Python optimizations;
* measured performance improvements;
* resource-usage considerations;
* the checkpoint/resume or failure-recovery strategy;
* known limitations or trade-offs.

A concise technical explanation is preferred over a lengthy general discussion. Use AI for that!

### 2. Public GitHub Repository
The complete submitted solution must be available in a **public GitHub repository** that does not require authentication or payment to access. Forking the official challenge repository is strongly recommended because it makes the modifications easier to inspect and reproduce.

Official base repository:  
`https://github.com/igorsiecz/kaggle_postgresql_challenge`

The repository must contain all source-code modifications required to reproduce the submitted solution. Do **not** commit passwords, SSH keys, PostgreSQL credentials, tokens, private server addresses, or other secrets.

### 3. Exact Submission Commit
The Kaggle Writeup must identify the exact Git commit that represents the final submission. For example:
```text
Repository:
[https://github.com/participant/repository](https://github.com/participant/repository)

Submission commit:
a83f8e2c1234567890...
```
Changes pushed to the repository after the competition deadline will therefore not alter the submitted solution.

## Tracks and Awards
**Main Track · Query Slayer: $100**  
For the cleanest, fastest, and most effective SQL query.

## Evaluation
This is a **performance and software-engineering challenge**. Submissions will be evaluated by the organizers on a standardized environment using databases generated exclusively with the official deterministic `generate_database.py` generator.

### Eligibility Gate — Required
Before receiving a score, a submission must pass all mandatory correctness and integrity checks.

| Requirement | Status |
| :--- | :--- |
| Produces the expected relational outputs from the official `raw_data` dataset | Pass / Fail |
| Preserves required source and destination validation guarantees | Pass / Fail |
| Preserves database version registration and required dump/version behavior | Pass / Fail |
| Does not modify the official dataset generator, its fixed seed, or the benchmark input data | Pass / Fail |
| Does not use hard-coded outputs or dataset-specific precomputed answers | Pass / Fail |
| Can be reproduced from the exact public Git commit submitted by the participant | Pass / Fail |

A submission that fails any mandatory requirement will not be eligible for the final ranking, regardless of its execution speed. Participants **may completely redesign the implementation** of these operations. The requirement is to preserve their functional guarantees, not necessarily their current implementation.

### Judging Rubric — 100 Points Total

| Criteria | Points Possible |
| :--- | :--- |
| **Expansion Performance** | **0–60** |
| **Failure Recovery & Consistency** | **0–20** |
| **Resource Efficiency** | **0–20** |
| **Total** | **100** |

#### 1. Expansion Performance — 60 points
The primary objective of the challenge is to minimize the expansion time reported by the DB Manager. The official timing metric is: `MEASURED PROCESSING TOTAL`

The judging team will run each valid submission against the same official benchmark workloads, generated with the same fixed generator and evaluated on the same hardware and software environment. Participant-reported benchmarks are useful for demonstrating development progress, but **the official ranking will be determined only by benchmarks reproduced by the judging team on the organizers' infrastructure**.

For each benchmark (j), performance points will be calculated relative to the fastest valid submission:

$$S_{i,j} = W_j \times \frac{T_{best,j}}{T_{i,j}}$$

where:
* $S_{i,j}$ is the score of submission (i) for benchmark (j);
* $W_j$ is the maximum number of points assigned to that benchmark;
* $T_{best,j}$ is the lowest valid `MEASURED PROCESSING TOTAL` obtained for that benchmark;
* $T_{i,j}$ is the corresponding time for submission (i).

The fastest valid submission therefore receives the full number of points for that benchmark, while slower submissions receive proportional scores. A solution that fails to complete a benchmark or produces invalid results receives **0 points for that benchmark**.

The long-term engineering target of the project is efficient expansion of datasets containing up to **300 million `raw_data` rows**.

#### 2. Failure Recovery & Consistency — 20 points
Long-running processing must remain reliable when communication or execution is interrupted.

#### 3. Resource Efficiency — 20 points
Execution time is the primary metric, but solutions must remain practical at large scale. The judging team will monitor resource usage during the official benchmarks: Peak RAM consumption and Temporary/intermediate disk usage.

Persistent storage that is part of the required final relational database is not considered temporary storage. Intermediate copies, staging data, temporary files, temporary tables, caches, and other additional storage introduced by the solution may be considered when evaluating this criterion.

### Tie-Breaking
If two or more submissions receive the same final score, ties will be resolved in the following order:
1. lower official `MEASURED PROCESSING TOTAL` on the largest benchmark;
2. lower peak RAM consumption on that benchmark;
3. lower temporary storage usage;
4. best coding good practices.

The organizers' reproduced benchmark results are final for ranking purposes.

## Judges
* **Igor Moreira** - Research Scientist, UFRGS
* **Henrique Falck Grimm**
* **Cassio Horta**

## Citation
Igor Moreira. Python & PostgreSQL Data Pipeline Optimization Challenge. https://www.kaggle.com/competitions/python-postgre-sql-data-pipeline-optimization-challenge, 2026. Kaggle.

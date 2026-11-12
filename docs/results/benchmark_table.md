| input | engine | rows | median s | min s | first run s | peak RSS MiB |
|---|---|---:|---:|---:|---:|---:|
| subset | pandas_default | 1,000,000 | 0.647 | 0.577 | 0.7 | 889.3 |
| subset | pandas_chunked_optimised | 1,000,000 | 0.674 | 0.658 | 0.674 | 446.0 |
| subset | polars_lazy | 1,000,000 | 0.044 | 0.043 | 0.061 | 389.2 |
| full | pandas_chunked_optimised | 4,906,867 | 4.053 | 4.047 | 4.147 | 401.6 |
| full | polars_lazy | 4,906,867 | 0.145 | 0.144 | 0.145 | 639.6 |

| input | engine | rows | median s | min s | first run s | peak RSS MiB |
|---|---|---:|---:|---:|---:|---:|
| subset | pandas_default | 1,000,000 | 0.6 | 0.597 | 0.61 | 869.4 |
| subset | pandas_chunked_optimised | 1,000,000 | 0.684 | 0.682 | 0.682 | 424.7 |
| subset | polars_lazy | 1,000,000 | 0.049 | 0.046 | 0.049 | 385.7 |
| full | pandas_chunked_optimised | 4,906,867 | 4.314 | 4.141 | 4.141 | 409.5 |
| full | polars_lazy | 4,906,867 | 0.187 | 0.14 | 0.14 | 624.5 |

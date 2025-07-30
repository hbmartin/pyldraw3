window.BENCHMARK_DATA = {
  "lastUpdate": 1753883804786,
  "repoUrl": "https://github.com/hbmartin/pyldraw3",
  "entries": {
    "Benchmark": [
      {
        "commit": {
          "author": {
            "email": "harold.martin@gmail.com",
            "name": "Harold Martin",
            "username": "hbmartin"
          },
          "committer": {
            "email": "harold.martin@gmail.com",
            "name": "Harold Martin",
            "username": "hbmartin"
          },
          "distinct": true,
          "id": "06225dba7e07968a927d124deaf0d957ed5cdc67",
          "message": "add pytest-benchmark and asv",
          "timestamp": "2025-07-30T07:56:12-06:00",
          "tree_id": "580e8a41d83dcea789833346b615eeb302f59338",
          "url": "https://github.com/hbmartin/pyldraw3/commit/06225dba7e07968a927d124deaf0d957ed5cdc67"
        },
        "date": 1753883804515,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_geometry.py::test_matrix_multiplication",
            "value": 424933.908451389,
            "unit": "iter/sec",
            "range": "stddev: 4.160929496183848e-7",
            "extra": "mean: 2.353307138148512 usec\nrounds: 66234"
          },
          {
            "name": "benchmarks/test_geometry.py::test_vector_operations",
            "value": 947443.3093421741,
            "unit": "iter/sec",
            "range": "stddev: 2.9111290781823025e-7",
            "extra": "mean: 1.0554721218035905 usec\nrounds: 199601"
          },
          {
            "name": "benchmarks/test_geometry.py::test_identity_matrix_creation",
            "value": 2005521.6479566158,
            "unit": "iter/sec",
            "range": "stddev: 5.1342045952242124e-8",
            "extra": "mean: 498.6233885926283 nsec\nrounds: 99711"
          }
        ]
      }
    ]
  }
}
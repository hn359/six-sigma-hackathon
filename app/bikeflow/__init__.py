"""BikeFlow QC: the Analyze and Improve module (H-09, H-10).

  config.py   every assumption as a setting (5 stations x 20 docks, 120 bikes, 06:00-22:00, 15 min)
  data.py     the data contract: any station-snapshot CSV -> clean readings
  qc.py       the statistic: slot-adjusted I-MR chart (plain function, tested)
  analyze.py  inventory, net flow, SPC and projection views over a dataset
  plan.py     the redistribution plan (now) and the 10 PM overnight plan
  api.py      FastAPI router; no statistics there
"""

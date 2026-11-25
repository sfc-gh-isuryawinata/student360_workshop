import importlib, sys
sys.path.insert(0, __file__.rsplit('/',1)[0])
for m in sys.argv[1:] or ["nb00","nb01","nb02","nb03","nb04","nb05","nb06","nb07"]:
    try: importlib.import_module(m)
    except ModuleNotFoundError as e:
        if e.name != m: raise

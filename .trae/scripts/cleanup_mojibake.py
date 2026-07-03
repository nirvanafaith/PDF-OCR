import os
import shutil

base = r'c:\Users\E-VR\Documents\trae_projects'
target = os.path.join(base, '妯牎')
if os.path.isdir(target):
    shutil.rmtree(target)
    print('Removed:', target)
else:
    print('Not found:', target)

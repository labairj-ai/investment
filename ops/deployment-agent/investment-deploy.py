"""Root-owned installed launcher; imports only the reviewed controller tree."""
import runpy
import sys
sys.path.insert(0,'/opt/investment-deployment-controller')
runpy.run_module('deployment_agent',run_name='__main__')

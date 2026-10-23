import runpy
import sys
sys.path.insert(0,'/opt/investment-deployment-controller')
runpy.run_module('deployment_agent.observer',run_name='__main__')

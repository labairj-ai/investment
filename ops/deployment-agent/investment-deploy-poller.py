import runpy
import sys
sys.path.insert(0,'/opt/investment-deployment-controller')
runpy.run_module('deployment_agent.poller',run_name='__main__')

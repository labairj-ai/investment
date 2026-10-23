"""Operator service entry; provider/image selection is external trusted config."""
import os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dev_agent.cli import main
main(['supervised-cycle','--root',str(Path(__file__).resolve().parents[1]),'--model',os.environ['DEV_AGENT_BUILDER_MODEL'],'--review-model',os.environ['DEV_AGENT_REVIEW_MODEL'],'--image',os.environ['DEV_AGENT_VALIDATOR_IMAGE']])

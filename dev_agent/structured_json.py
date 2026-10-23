"""Reject ambiguous duplicate fields and non-JSON numeric constants in decisions."""
import json


def loads(text):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('duplicate structured decision field')
            result[key]=value
        return result
    def constant(value):raise ValueError('non-finite JSON decision value')
    return json.loads(text,object_pairs_hook=pairs,parse_constant=constant)

"""Load the stdlib-only Windows lifetime bridge without importing bpy/addon code."""
import importlib.util
import os
from entry import ROOT
spec=importlib.util.spec_from_file_location('_toyxyz_windows_lifetime',ROOT/'addons/toyxyz_motion_ai_tool/lifetime.py')
jobs=importlib.util.module_from_spec(spec);spec.loader.exec_module(jobs)

def join():jobs.join_from_environment()
def identity():return jobs.identity()
def job_name(instance):return os.environ.get(jobs.ENV) or jobs.prefix(ROOT)+instance

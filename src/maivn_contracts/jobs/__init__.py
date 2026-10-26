"""Bounded hosted jobs are opt-in and do not resume after replica loss."""

from maivn_contracts.jobs.model import HostedJobOptions, HostedJobStatus, JobTerminalReason

__all__ = ['HostedJobOptions', 'HostedJobStatus', 'JobTerminalReason']

'''Pure attribution helper for the per-worker report, kept independent of the
ORM so the money-adjacent logic it powers is exercisable without a database.

`finishing_worker` reads a complaint's lifecycle events (assigned / reassigned
rows carry the worker that event put onto the complaint) and returns the worker
who held the job at `finished_at` — the last assignment that landed at or
before the finish stamp. Events that happened after the job finished (a
post-hoc reassign or unassign) don't move attribution: the finished job stays
with whoever actually finished it.

Jobs that predate the worker column on complaint_event have no relevant events
and get the complaint's current `worker` FK as the fallback.'''
from django.utils import timezone


def finishing_worker(job):
    '''The worker assigned to `job` when it finished. Duck-typed inputs:
    `job.events` (a queryset, manager, or list) iterates {action, created_at,
    worker}; `job.finished_at` and `job.worker` are optional.'''
    worker = None
    finished_at = getattr(job, 'finished_at', None)
    events = getattr(job, 'events', None) or ()
    if hasattr(events, 'all'):
        # A (prefetched) related manager iterates via .all() — which still
        # serves the prefetch cache when one is set.
        events = events.all()
    for ev in events:
        if ev.action not in ('assigned', 'reassigned'):
            continue
        if finished_at is not None and ev.created_at is not None \
                and ev.created_at > finished_at:
            continue
        # Iteration is in log order (created_at, event_id): the last matching
        # assignment before/at finish wins.
        worker = ev.worker
    if worker is not None:
        return worker
    return getattr(job, 'worker', None)


def _demo():
    '''One runnable check: fails if finishing-worker attribution regresses.'''
    class Ev:
        def __init__(self, action, created_at, worker):
            self.action = action
            self.created_at = created_at
            self.worker = worker

    class Job:
        def __init__(self, events, finished_at, worker=None):
            self.events = events
            self.finished_at = finished_at
            self.worker = worker

    now = timezone.now()
    earlier = now - timezone.timedelta(hours=2)
    mid = now - timezone.timedelta(hours=1)
    later = now + timezone.timedelta(hours=1)

    a, b, c = object(), object(), object()

    # No events at all → the FK fallback.
    assert finishing_worker(Job([], now, a)) is a

    # Events after the finish stamp are ignored: a post-hoc reassign of an
    # already-finished job must not move the job to the new worker.
    job = Job([Ev('assigned', earlier, a), Ev('reassigned', later, b)], mid, a)
    assert finishing_worker(job) is a

    # Mid-job reassign: brought onto B before finish → B gets the job.
    job = Job([Ev('assigned', earlier, a), Ev('reassigned', mid, b)], now, b)
    assert finishing_worker(job) is b

    # Unassigned mid-job then reassigned: the last pre-finish assignment wins.
    job = Job(
        [Ev('assigned', earlier, a), Ev('unassigned', mid, a), Ev('assigned', mid, c)],
        now, c,
    )
    assert finishing_worker(job) is c

    # Stamp-equal boundary: an assignment exactly at finished_at counts.
    job = Job([Ev('assigned', now, b)], now, b)
    assert finishing_worker(job) is b

    print('worker_report_util: all assertions passed')


if __name__ == '__main__':
    _demo()
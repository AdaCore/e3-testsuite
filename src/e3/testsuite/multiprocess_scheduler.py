from __future__ import annotations

"""Special scheduler for efficient use of subprocesses.

When the parallelism level is high enough, using threads to dispatch the work
to do creates too much contention on Python's GIL. Since `e3.job.scheduler` is
based on threads, this module provides an alternative API to avoid creating
threads, dispatching work using subprocesses instead.
"""

import itertools
import logging
import time
from typing import Callable, Generic, List, Optional, TYPE_CHECKING, TypeVar

from e3.collection.dag import DAGIterator
from e3.env import Env
from e3.os.process import Run

if TYPE_CHECKING:
    from e3.collection.dag import DAG
    from e3.testsuite.driver import TestDriver
    from e3.testsuite.running_status import RunningStatus


logger = logging.getLogger("testsuite.process_scheduler")


class Worker:
    """Abstract class to represent units of work for the scheduler."""

    index_generator = iter(itertools.count(1))
    """Generate unique indexes for each worker."""

    def __init__(
        self,
        uid: str,
        driver: TestDriver,
        callback_name: str,
        slot: int,
        env: Env,
    ):
        """Initialize a Worker instance.

        :param uid: Unique identifier for this worker.
        :param driver: Test driver handling the work to do.
        :param callback_name: Name of the `driver` method to call for the work
            to do.
        :param slot: ID for the slot this worker was assigned to. At all time,
            all running workers are assigned different slots.
        """
        self.uid = uid
        self.driver = driver
        self.callback_name = callback_name
        self.slot = slot
        self.env = env
        self.index = next(self.index_generator)

        self.process = self.start()
        """Process that executes this test fragment."""

    def start(self) -> Run:
        """Create and return the subprocess to do the work.

        All subclasses must override this.
        """
        raise NotImplementedError

    def poll(self, scheduler: MultiprocessScheduler) -> bool:
        """Return whether the subprocess is still running.

        If it is, the caller should invoke
        `MultiprocessScheduler.collect_result` on it.
        """
        if self.process.poll() is not None:
            self.process.wait()
            return False
        else:
            return True


WorkData = TypeVar("WorkData")
"""Type that contains all the information needed to do some unit of work."""

SomeWorker = TypeVar("SomeWorker", bound=Worker)
"""Worker subclass to start some unit of work."""

JobFactoryCallback = Callable[[str, WorkData, int], SomeWorker]
"""Callback to create a Worker instance from work data.

Arguments are:

* UID for this unit of work;
* data for the work to do;
* slot ID for the new worker.

Returned value is the Worker instance.
"""

CollectResultCallback = Callable[[SomeWorker], None]
"""Callback to extract work result from a worker."""


class MultiprocessScheduler(Generic[WorkData, SomeWorker]):
    """Scheduler to dispatch units of work to subprocesses."""

    def __init__(
        self,
        dag: DAG,
        job_factory: JobFactoryCallback,
        collect_result: CollectResultCallback,
        running_status: RunningStatus,
        jobs: int = 0,
        dyn_poll_interval: bool = True,
    ):
        """Initialize a MultiprocessScheduler instance.

        :param dag: DAG in which nodes represent units of work to do and edges
            represent dependencies between them.
        :param job_factory: Callback to turn DAG nodes into corresponding
            Worker instances.
        :param collect_result: Callback to extract work result from a worker.
        :param running_status: Testsuite running status, used to detect when
            the testsuite is aborted because of too many failures.
        :param jobs: Maximum of worker allowed to run in parallel. If left to
            0, use the number of available cores on the current machine.
        :param dyn_poll_interval: If True the interval between each polling
            iteration is automatically updated. Otherwise it's set to 0.1
            seconds.
        """
        e = Env()
        self.parallelism = jobs or e.build.cpu.cores
        self.dag = dag

        self.workers: List[Optional[SomeWorker]] = [None] * self.parallelism
        """
        List of active workers. Indexes in this list correspond to slot IDs
        passed to workers: `self.workers[N].slot == N` for all present
        wor,kers. When the worker is done, we just replace it with None, and
        when a slot is None we can create a new worker for it.
        """

        self.iterator = DAGIterator(self.dag, enable_busy_state=True)
        """Iterator to get ready-to-run units of work."""

        self.job_factory = job_factory
        self.collect_result = collect_result
        self.running_status = running_status

        self.active_workers = 0
        """Equivalent to the number of non-None slots in ``self.workers``."""

        self.poll_interval = 0.1
        """Time (in seconds) to wait between each round of worker polling."""

        self.dyn_poll_interval = dyn_poll_interval

        self.no_free_item = False
        """
        True if there is work waiting to be executed, False if all work to be
        scheduled depends on work that hasn't completed.
        """

        self.no_work_left = False
        """
        True if we processed all items from ``self.iterator`` (i.e. we got a
        ``StopIteration`` exception from it).
        """

    @property
    def has_free_slots(self) -> bool:
        """Return whether there is a free slot to spawn a worker."""
        return self.active_workers < self.parallelism

    def spawn_worker(self, uid: str, data: WorkData, slot: int) -> None:
        """Create a worker and assign it to the given slot."""
        assert self.workers[slot] is None
        worker = self.job_factory(uid, data, slot)
        self.workers[slot] = worker
        self.active_workers += 1

    def release_worker(self, slot: int) -> None:
        """Release a worker, freeing the corresponding slot."""
        assert self.workers[slot] is not None
        self.workers[slot] = None
        self.active_workers -= 1

    def run(self) -> None:
        """Run the loop to execute all units of work."""
        # Run the main loop until all fragments are started and have
        # completed. We need to wait for started fragments when catching a
        # KeybordInterrupt exception (user asked to stop, or the testsuite
        # decided to stop because of too many consecutive failures).
        try:
            while self.active_workers > 0 or not self.no_work_left:
                self.poll()

        except KeyboardInterrupt:  # interactive-only
            logger.error(
                "Scheduling abortion requested, waiting for all active"
                " workers..."
            )

            # Poll active workers at regular but small interval until they all
            # complete.
            while self.active_workers > 0:
                for slot, worker in enumerate(self.workers):
                    if worker is None:
                        continue

                    # If the worker has completed, release it, but do not
                    # collect it: we are not interested in test results created
                    # after testsuite abortion.
                    still_running = worker.poll(self)
                    if not still_running:
                        self.release_worker(slot)
                        self.iterator.leave(worker.uid)

                time.sleep(0.1)

            # Let the caller know about abnormal interruption
            raise

    def poll(self) -> None:
        # Perform a linear scan to find free slots: allocate a worker for each
        # of them.
        #
        # Note that there is no need to go through this if we already know
        # that:
        #
        # * there is no work left to schedule;
        # * all slots are occupied by workers;
        # * all pending work units depend on non-completed units.
        if (
            not self.no_work_left
            and self.has_free_slots
            and not self.no_free_item
        ):
            for slot, worker in enumerate(self.workers):
                if worker is None:
                    # Three possible cases:
                    #
                    # * At least one work unit can be scheduled right now: the
                    #   call to `next` return non-None results.
                    #
                    # * There are work units left, but they all depend on
                    #   non-completed other units: we get two None values.
                    #
                    # * All work units were scheduled: the call to `next`
                    #   raises a StopIteration exception.
                    try:
                        uid, work_data = next(self.iterator)
                    except StopIteration:
                        self.no_work_left = True
                        break

                    if work_data is None:
                        # All pending work units depend on non-completed units.
                        # There is no need to continue scanning workers.
                        self.no_free_item = True
                        break

                    assert isinstance(uid, str)
                    self.spawn_worker(uid, work_data, slot)

                    # No need to continue scanning if that was the last free
                    # slot.
                    if not self.has_free_slots:
                        break

        # Now, wait for some work units to complete if either:
        #
        # * all worker slots are busy;
        # * all pending work depends on non-completed work;
        # * there is no work left to schedule but we have some workers to wait.
        logger.debug("Wait for free worker")
        poll_counter = 0
        while (
            not self.has_free_slots
            or self.no_free_item
            or (self.no_work_left and self.active_workers > 0)
        ):
            poll_counter += 1
            for slot, worker in enumerate(self.workers):
                # If the worker has completed, release the corresponding slot
                if worker is not None and not worker.poll(self):
                    self.release_worker(slot)
                    self.iterator.leave(worker.uid)
                    self.no_free_item = False

                    # Collect results from this worker. If we decide to abort
                    # the testsuite because of too many failures at that point,
                    # consider that there is no work left, so that no new
                    # worker is spawned past this.
                    self.collect_result(worker)
                    if self.running_status.aborted_too_many_failures:
                        self.no_work_left = True

            time.sleep(self.poll_interval)

        # Adjust the poll interval if it is dynamic
        if self.dyn_poll_interval:
            self.poll_interval = compute_next_dyn_poll(
                poll_counter, self.poll_interval
            )


def compute_next_dyn_poll(
    poll_counter: int,
    poll_interval: float,
) -> float:  # all: no-cover
    """Adjust the polling interval.

    :param poll_counter: Number of times we had to scan the whole pool of
        workers before finding one which completed a job during the previous
        poll session.
    :param poll_interval: Delay (in seconds) between each scan of the pool of
        workers during the previous poll session.

    :return: The delay (still in seconds) between each scan for the next poll
        session.
    """
    # If we poll too often (towards busy waiting), the scheduler will waste
    # computing time. If we poll too little, we will wait for too long before
    # spawning new workers and thus we will not maximize the use of cores.
    if poll_counter > 8 and poll_interval < 1.0:
        poll_interval *= 1.25
        logger.debug(f"Increase poll interval to {poll_interval}")
    elif poll_interval > 0.0001:
        poll_interval *= 0.75
        logger.debug(f"Decrease poll interval to {poll_interval}")
    return poll_interval

"""N-thread hammer over the race-free derived-state holder (RECON-04).

Plan 04-01's Wave-0 concurrency proof: while N threads drive
:func:`web.derived.holder.get_or_rebuild` with alternating stamps, other threads
publish and read the simulation slot. The holder must never let a reader observe
a half-built mapping, a stamp/data generation mismatch, or a torn sim payload —
and no exception may escape any thread.

The stamp sentinel is the key invariant: ``build`` returns
``{"gen": <stamp gen>}``, and :func:`get_or_rebuild` is specified to ALWAYS return
data built for the stamp it was called with (fast-path match or a locked rebuild
with that exact stamp). So ``data["gen"] == requested_stamp.entries[0][1]`` must
hold on every iteration, under any interleaving.
"""

from __future__ import annotations

import threading

from football_core.store_stamp import StoreStamp

N_THREADS = 12
ITERATIONS = 100


def test_n_thread_hammer() -> None:
    from web.derived import holder

    holder.reset()
    exceptions: list[BaseException] = []
    stamps = [
        StoreStamp(entries=(("results", i, 10 + i),)) for i in range(4)
    ]
    barrier = threading.Barrier(N_THREADS)

    def worker(idx: int) -> None:
        try:
            barrier.wait()
            for i in range(ITERATIONS):
                stamp = stamps[(idx + i) % len(stamps)]

                def build(_stamp=stamp):
                    return {"gen": _stamp.entries[0][1]}, "results"

                data = holder.get_or_rebuild("ucl", stamp, build)

                # (a) every return is a frozen mapping
                try:
                    data["gen"] = -1  # type: ignore[index]
                    raise AssertionError("returned mapping is mutable")
                except TypeError:
                    pass

                # (b) no stamp/data generation mismatch
                assert data["gen"] == stamp.entries[0][1], (
                    f"thread {idx}: data gen {data['gen']} != "
                    f"stamp gen {stamp.entries[0][1]}"
                )

                # (d) sim slot: complete payload or empty, never torn
                holder.publish_sim("ucl", {"status": "completed", "n": i})
                sim = holder.read_sim("ucl")
                if sim:
                    assert sim["status"] == "completed"
        except BaseException as exc:  # noqa: BLE001 - collect, never escape
            exceptions.append(exc)

    threads = [
        threading.Thread(target=worker, args=(idx,)) for idx in range(N_THREADS)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert exceptions == [], f"{len(exceptions)} thread(s) raised: {exceptions[:3]}"
    holder.reset()

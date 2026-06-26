import logging
import re
import threading


def test_run_id_filter_stamps_record():
    from observability.run_context import RunIdFilter, set_run_id
    set_run_id("run-0830")
    f = RunIdFilter()
    record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
    f.filter(record)
    assert record.run_id == "run-0830"


def test_run_id_default_is_dash():
    from observability import run_context
    run_context._run_id.set("-")
    assert run_context.get_run_id() == "-"


def test_new_run_id_format():
    from observability.run_context import new_run_id
    rid = new_run_id()
    assert re.match(r"^run-\d{4}$", rid), f"Unexpected format: {rid}"


def test_thread_isolation():
    from observability.run_context import set_run_id, get_run_id
    results = {}

    def worker(name, rid):
        set_run_id(rid)
        import time; time.sleep(0.05)
        results[name] = get_run_id()

    t1 = threading.Thread(target=worker, args=("a", "run-0100"))
    t2 = threading.Thread(target=worker, args=("b", "run-0200"))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert results["a"] == "run-0100"
    assert results["b"] == "run-0200"

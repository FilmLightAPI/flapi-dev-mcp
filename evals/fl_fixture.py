"""FLAPI side of the eval fixture. Runs under a Python that can `import flapi`
(the target build's venv), driven by evals/fixture.py via JSON on argv.

    fl_fixture.py setup  '{"job": "flapi_eval", "scenes": ["a", "b"], "media": ["/x/1.mov"]}'
    fl_fixture.py marks  '{"job": "flapi_eval", "scene": "a"}'
    fl_fixture.py teardown '{"job": "flapi_eval"}'

Prints one JSON object on stdout.
"""

import json
import sys

import flapi

HOST = "localhost"


def _connect():
    conn = flapi.Connection(HOST)
    conn.connect()
    return conn


def setup(conn, job, scenes, media):
    jm = conn.JobManager
    if jm.job_exists(HOST, job):
        jm.delete_job(HOST, job, 1)
    jm.create_job(HOST, job)
    opts = {"format": "HD 1920x1080", "colourspace": "FilmLight_TLog_EGamut",
            "frame_rate": 24.0, "field_order": flapi.FIELDORDER_PROGRESSIVE}
    out = {}
    for name in scenes:
        scene = conn.Scene.new_scene(flapi.ScenePath({"Host": HOST, "Job": job, "Scene": name}), opts)
        scene.start_delta("Insert eval media")
        for path in media:
            seq = conn.SequenceDescriptor.get_for_file(path)
            shot = scene.insert_sequence(seq, flapi.INSERT_END, None, None, None)
            shot.release()
            seq.release()
        scene.end_delta()
        out[name] = scene.get_num_shots()
        scene.save_scene()
        scene.close_scene()
        scene.release()
    return {"ok": True, "shots": out}


def marks(conn, job, scene):
    s = conn.Scene.open_scene(flapi.ScenePath({"Host": HOST, "Job": job, "Scene": scene}),
                              {flapi.OPENFLAG_READ_ONLY})
    try:
        ids = s.get_mark_ids()
        notes = []
        for i in ids:
            m = s.get_mark(i)
            notes.append(m.get_note_text())
            m.release()
        return {"ok": True, "count": len(ids), "notes": notes}
    finally:
        s.close_scene()
        s.release()


def teardown(conn, job):
    jm = conn.JobManager
    if jm.job_exists(HOST, job):
        jm.delete_job(HOST, job, 1)
    return {"ok": True}


def main():
    cmd, args = sys.argv[1], json.loads(sys.argv[2])
    conn = _connect()
    try:
        res = {"setup": setup, "marks": marks, "teardown": teardown}[cmd](conn, **args)
    except flapi.FLAPIException as e:
        res = {"ok": False, "error": str(e)}
    finally:
        conn.close()
    print(json.dumps(res))


if __name__ == "__main__":
    main()

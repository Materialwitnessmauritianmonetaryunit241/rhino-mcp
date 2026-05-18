// RhinoAIBridge v4.7 -- JobManager.cs
// Async job system for long-running execute_script calls.
// Jobs run on the Rhino UI thread (RhinoApp.InvokeOnUiThread) so they can
// touch RhinoDoc safely, but they are launched fire-and-forget so the MCP
// call returns immediately with a job_id for polling.

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using Rhino;

namespace RhinoAIBridge
{
    public enum JobStatus { Pending, Running, Completed, Failed, Cancelled }

    public class Job
    {
        public string Id      { get; } = Guid.NewGuid().ToString("N")[..12];
        public string Label   { get; set; }
        public JobStatus Status { get; set; } = JobStatus.Pending;
        public JObject  Result  { get; set; }
        public string   Error   { get; set; }
        public DateTime Created { get; } = DateTime.UtcNow;
        public DateTime? Finished { get; set; }
        public bool CancelRequested { get; set; }
    }

    public static class JobManager
    {
        private static readonly ConcurrentDictionary<string, Job> _jobs = new();

        // Prune jobs older than this to avoid unbounded growth.
        private static readonly TimeSpan _maxAge = TimeSpan.FromHours(4);

        /// <summary>
        /// Enqueue a job that will execute <paramref name="work"/> on the UI thread.
        /// Returns the new Job (status = Pending).
        /// </summary>
        public static Job Enqueue(string label, Func<Job, JObject> work)
        {
            Prune();
            var job = new Job { Label = label ?? "script" };
            _jobs[job.Id] = job;

            // Fire-and-forget on Rhino's UI thread.
            RhinoApp.InvokeOnUiThread(new Action(() =>
            {
                if (job.CancelRequested)
                {
                    job.Status   = JobStatus.Cancelled;
                    job.Finished = DateTime.UtcNow;
                    return;
                }
                job.Status = JobStatus.Running;
                try
                {
                    job.Result   = work(job);
                    job.Status   = job.CancelRequested ? JobStatus.Cancelled : JobStatus.Completed;
                }
                catch (Exception ex)
                {
                    job.Status = JobStatus.Failed;
                    job.Error  = ex.Message;
                }
                finally
                {
                    job.Finished = DateTime.UtcNow;
                }
            }));

            return job;
        }

        public static Job Get(string id)
            => _jobs.TryGetValue(id, out var j) ? j : null;

        public static JObject GetStatus(string id)
        {
            var j = Get(id);
            if (j == null) return new JObject { ["status"] = "error", ["message"] = $"Job not found: {id}" };
            return new JObject
            {
                ["status"]     = "ok",
                ["job_id"]     = j.Id,
                ["job_status"] = j.Status.ToString().ToLower(),
                ["label"]      = j.Label,
                ["created_at"] = j.Created.ToString("o"),
                ["finished_at"]= j.Finished?.ToString("o"),
                ["error"]      = j.Error,
            };
        }

        public static JObject GetResult(string id)
        {
            var j = Get(id);
            if (j == null) return new JObject { ["status"] = "error", ["message"] = $"Job not found: {id}" };
            if (j.Status == JobStatus.Running || j.Status == JobStatus.Pending)
                return new JObject { ["status"] = "pending", ["job_id"] = j.Id, ["job_status"] = j.Status.ToString().ToLower() };
            if (j.Status == JobStatus.Failed)
                return new JObject { ["status"] = "error", ["job_id"] = j.Id, ["message"] = j.Error ?? "Job failed" };
            if (j.Status == JobStatus.Cancelled)
                return new JObject { ["status"] = "cancelled", ["job_id"] = j.Id };
            // Completed
            var r = j.Result ?? new JObject();
            r["job_id"] = j.Id;
            return r;
        }

        public static JObject Cancel(string id)
        {
            var j = Get(id);
            if (j == null) return new JObject { ["status"] = "error", ["message"] = $"Job not found: {id}" };
            if (j.Status == JobStatus.Completed || j.Status == JobStatus.Failed)
                return new JObject { ["status"] = "error", ["message"] = $"Job already finished ({j.Status})" };
            j.CancelRequested = true;
            if (j.Status == JobStatus.Pending)
            {
                j.Status   = JobStatus.Cancelled;
                j.Finished = DateTime.UtcNow;
            }
            return new JObject { ["status"] = "ok", ["job_id"] = j.Id, ["message"] = "Cancellation requested" };
        }

        public static JObject ListJobs()
        {
            var arr = new JArray();
            foreach (var kv in _jobs)
                arr.Add(GetStatus(kv.Key));
            return new JObject { ["status"] = "ok", ["jobs"] = arr, ["count"] = arr.Count };
        }

        private static void Prune()
        {
            var cutoff = DateTime.UtcNow - _maxAge;
            foreach (var kv in _jobs)
            {
                var j = kv.Value;
                if ((j.Status == JobStatus.Completed || j.Status == JobStatus.Failed || j.Status == JobStatus.Cancelled)
                    && j.Finished.HasValue && j.Finished.Value < cutoff)
                    _jobs.TryRemove(kv.Key, out _);
            }
        }
    }
}

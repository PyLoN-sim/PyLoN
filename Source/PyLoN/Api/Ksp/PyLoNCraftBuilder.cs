using System;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using UnityEngine;

namespace PyLoN
{
    /// <summary>Local, session-bound editor requests. No flight socket or ROS dependency.</summary>
    [KSPAddon(KSPAddon.Startup.EditorAny, false)]
    public sealed class PyLoNCraftBuilder : MonoBehaviour
    {
        private const int MaxRequestBytes = 1024 * 1024;
        private string directory;
        private string session;
        private double nextPoll;
        private double nextStatus;
        private int readyFrames;
        private static readonly UTF8Encoding Utf8 = new UTF8Encoding(false, true);

        private static double Now { get { return (DateTime.UtcNow - new DateTime(1970, 1, 1)).TotalSeconds; } }
        private static bool EditorReady
        {
            get { return HighLogic.LoadedSceneIsEditor && HighLogic.CurrentGame != null
                && EditorDriver.fetch != null && !EditorDriver.fetch.restartingEditor
                && EditorLogic.fetch != null && EditorLogic.fetch.ship != null && PartLoader.LoadedPartsList != null; }
        }
        private bool Ready { get { return EditorReady && readyFrames >= 5; } }

        public void Start()
        {
            directory = Path.Combine(KSPUtil.ApplicationRootPath, "PluginData", "PyLoN", "CraftBuilder");
            session = Guid.NewGuid().ToString("N");
            try
            {
                Directory.CreateDirectory(Path.Combine(directory, "requests"));
                Directory.CreateDirectory(Path.Combine(directory, "results"));
                PublishStatus();
                Debug.Log("[PyLoN] Craft builder ready in " + directory);
            }
            catch (Exception ex) { Debug.LogError("[PyLoN] Craft builder: " + ex.Message); enabled = false; }
        }

        public void Update()
        {
            readyFrames = EditorReady ? Math.Min(readyFrames + 1, 5) : 0;
            double now = Now;
            if (now < nextPoll) return;
            nextPoll = now + 0.1;
            try
            {
                if (now >= nextStatus) { PublishStatus(); nextStatus = now + 1; }
                if (!Ready) return;
                // Handle one request per tick. Files are claimed before parsing and never retried.
                foreach (string path in Directory.EnumerateFiles(Path.Combine(directory, "requests"), "*.json"))
                {
                    string id = Path.GetFileNameWithoutExtension(path);
                    if (!Regex.IsMatch(id, "^[a-f0-9]{32}\\z")) continue;
                    Handle(path, id);
                    break;
                }
            }
            catch (Exception ex) { Debug.LogError("[PyLoN] Craft builder: " + ex.Message); }
        }

        private void Handle(string path, string id)
        {
            string claimed = path + ".processing";
            try { File.Move(path, claimed); }
            catch (IOException) { return; }
            var result = new CraftBuilderResult { id = id };
            try
            {
                // A duplicate delivery cannot build a second craft.
                string resultPath = Path.Combine(directory, "results", id + ".json");
                if (File.Exists(resultPath)) return;
                if (new FileInfo(claimed).Length > MaxRequestBytes) throw new ArgumentException("Request exceeds 1 MiB.");
                var request = CraftBuilderCodec.ReadRequest(File.ReadAllText(claimed, Utf8));
                if (request == null || request.version != 1 || request.id != id || request.session != session)
                    throw new ArgumentException("Invalid request version, id or editor session. Re-run the command.");
                if (double.IsNaN(request.expiresAt) || double.IsInfinity(request.expiresAt)
                    || request.expiresAt < Now || request.expiresAt > Now + 125)
                    throw new ArgumentException("Request expired or has an invalid deadline.");
                switch (request.command)
                {
                    case "parts": result.parts = CraftAssembly.Catalog(request.filter); break;
                    case "inspect": result.parts = CraftAssembly.Inspect(EditorLogic.fetch.ship); break;
                    case "build":
                        if (request.spec == null) throw new ArgumentException("Missing craft specification.");
                        request.spec.Validate();
                        if (request.spec.facility != EditorDriver.editorFacility.ToString())
                            throw new ArgumentException("Open the " + request.spec.facility + " before building this craft.");
                        if (request.load && EditorLogic.fetch.ship.parts.Count != 0)
                            throw new ArgumentException("--load requires an empty editor. Save your current craft and choose New first, or omit --load.");
                        CraftAssembly.Build(request.spec, id, result);
                        if (request.load)
                        {
                            if (!Ready || EditorLogic.fetch.ship.parts.Count != 0)
                                throw new InvalidOperationException("Craft saved, but the editor is no longer empty and ready. Load the saved craft manually.");
                            EditorLogic.LoadShipFromFile(result.craftPath);
                            EditorDriver.StartupBehaviour = EditorDriver.StartupBehaviours.LOAD_FROM_CACHE;
                            readyFrames = 0;
                            result.loaded = true;
                        }
                        break;
                    default: throw new ArgumentException("Unknown craft builder command.");
                }
                result.ok = true;
            }
            catch (Exception ex)
            {
                result.error = ex.Message;
                Debug.LogWarning("[PyLoN] Craft builder request " + id + ": " + ex);
            }
            finally
            {
                try { if (File.Exists(claimed)) File.Delete(claimed); }
                catch (IOException) { }
            }
            string response;
            try { response = CraftBuilderCodec.WriteResult(result); }
            catch (Exception ex)
            {
                // A large catalog must return an error instead of silently timing out.
                result.ok = false;
                result.parts = new CraftPartReport[0];
                result.error = "Response could not be encoded: " + ex.Message + ". For parts, use a narrower --filter.";
                response = CraftBuilderCodec.WriteResult(result);
            }
            WriteAtomic(Path.Combine(directory, "results", id + ".json"), response);
        }

        private void PublishStatus(bool closing = false)
        {
            WriteAtomic(Path.Combine(directory, "status.json"), CraftBuilderCodec.WriteStatus(new CraftBuilderStatus
            {
                session = session, updatedAt = Now, ready = !closing && Ready,
                facility = EditorDriver.editorFacility.ToString(), save = HighLogic.SaveFolder
            }));
        }

        internal static void WriteAtomic(string path, string text)
        {
            string temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                File.WriteAllText(temporary, text, Utf8);
                if (File.Exists(path)) File.Replace(temporary, path, null);
                else File.Move(temporary, path);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }

        public void OnDestroy()
        {
            if (directory == null) return;
            try { PublishStatus(true); }
            catch (Exception ex) { Debug.LogWarning("[PyLoN] Craft builder shutdown: " + ex.Message); }
        }
    }

    internal sealed class CraftBuilderStatus
    {
        public int version = 1;
        public string session;
        public double updatedAt;
        public bool ready;
        public string facility;
        public string save;
    }

    internal sealed class CraftBuilderRequest
    {
        public int version;
        public string id;
        public string session;
        public double expiresAt;
        public string command;
        public string filter;
        public bool load;
        public CraftSpecification spec;
    }

    internal sealed class CraftBuilderResult
    {
        public int version = 1;
        public string id;
        public bool ok;
        public string error = "";
        public string craftPath = "";
        public bool loaded;
        public CraftPartReport[] parts = new CraftPartReport[0];
    }

    internal sealed class CraftPartReport
    {
        public string id;
        public string part;
        public string title;
        public string parent;
        public double[] position;
        public double[] rotation;
        public int stage;
        public CraftNodeReport[] nodes;
        public bool surfaceAttach;
        public bool allowSurfaceAttach;
        public bool stackAttach;
        public bool allowStack;
    }

    internal sealed class CraftNodeReport
    {
        public string id;
        public double[] position;
        public double[] direction;
        public string attachedPart;
    }
}

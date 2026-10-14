// SpeakerWeave plugin for SimHub.
//
// SimHub knows which game is running. This plugin passes that on to SpeakerWeave,
// so SpeakerWeave can load the speaker setup chosen for that game, and it gives
// SimHub SpeakerWeave controls (volume, mute, setups ...) to put on wheel buttons,
// and SpeakerWeave's state as properties for dashboards.
//
// It talks to SpeakerWeave over the link SpeakerWeave opens on this PC only
// (127.0.0.1), with the secret code from SpeakerWeave's own settings file. It only
// sends something when the game changes, and asks for SpeakerWeave's state every
// two seconds, always off SimHub's data thread, so it costs SimHub nothing.
//
// Written for the C# compiler that comes with Windows (.NET Framework 4), so it can
// be built without Visual Studio: see build_plugin.bat.

using System;
using System.Globalization;
using System.IO;
using System.Net;
using System.Reflection;
using System.Text.RegularExpressions;
using System.Threading;
using GameReaderCommon;
using SimHub.Plugins;

[assembly: AssemblyTitle("SpeakerWeave for SimHub")]
[assembly: AssemblyDescription("Links SimHub with SpeakerWeave")]
[assembly: AssemblyCompany("Eli Smart")]
[assembly: AssemblyProduct("SpeakerWeave")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

namespace SpeakerWeave.SimHubPlugin
{
    [PluginDescription("Links SimHub with SpeakerWeave: SpeakerWeave learns which game is running and loads the speaker setup you chose for it, and SimHub gets SpeakerWeave controls and properties.")]
    [PluginAuthor("Eli Smart")]
    [PluginName("SpeakerWeave")]
    public class SpeakerWeavePlugin : IPlugin, IDataPlugin
    {
        public PluginManager PluginManager { get; set; }

        private static readonly string[] Actions = new string[] {
            "toggle_sound", "volume_up", "volume_down", "mute", "next_mode", "prev_mode",
            "toggle_bass", "toggle_upmix", "toggle_metronome", "slot_1", "slot_2", "slot_3", "slot_4" };

        private string lastGame = null;
        private DateTime nextStatus = DateTime.MinValue;
        private long nextSettingsTicks = 0;
        private volatile int port = 47800;
        private volatile string token = "";
        private volatile string statusJson = "";
        private volatile string gameQuery = null;
        private volatile bool connected;
        private int busy;

        public void Init(PluginManager pluginManager)
        {
            ReadSettings();
            this.AttachDelegate("Connected", () => connected);
            this.AttachDelegate("Running", () => Field("running") == "true");
            this.AttachDelegate("Muted", () => Field("muted") == "true");
            this.AttachDelegate("VolumeDb", () => Number("volume_db"));
            this.AttachDelegate("Mode", () => Field("mode"));
            this.AttachDelegate("Setup", () => Field("setup"));
            this.AttachDelegate("Game", () => Field("game"));
            foreach (string action in Actions)
            {
                string name = action;
                this.AddAction(name, (a, b) => Send(name));
            }
        }

        public void DataUpdate(PluginManager pluginManager, ref GameData data)
        {
            // runs for every frame of game data: only compare a name and the clock here
            string game = data.GameRunning ? (data.GameName ?? "") : "";
            if (game != lastGame)
            {
                lastGame = game;
                string car = "";
                string track = "";
                if (data.GameRunning && data.NewData != null)
                {
                    car = data.NewData.CarModel ?? "";
                    track = data.NewData.TrackName ?? "";
                }
                gameQuery = "name=" + Uri.EscapeDataString(game) + "&car=" + Uri.EscapeDataString(car)
                            + "&track=" + Uri.EscapeDataString(track);
                Send("game?" + gameQuery);
            }
            DateTime now = DateTime.UtcNow;
            if (now >= nextStatus)
            {
                nextStatus = now.AddSeconds(2);
                FetchStatus();
            }
        }

        public void End(PluginManager pluginManager)
        {
            // SimHub is closing or switching games: tell SpeakerWeave no game runs now
            if (!string.IsNullOrEmpty(lastGame) && connected)
            {
                Get(BaseUrl() + "game?name=");
            }
        }

        private void Send(string what)
        {
            ThreadPool.QueueUserWorkItem(delegate { Get(BaseUrl() + what); });
        }

        private void FetchStatus()
        {
            if (Interlocked.Exchange(ref busy, 1) == 1)
            {
                return;
            }
            ThreadPool.QueueUserWorkItem(delegate
            {
                try
                {
                    // the game goes along every time, so a SpeakerWeave started later still learns it
                    string query = gameQuery;
                    string text = Get(BaseUrl() + "status?client=simhub" + (query != null ? "&" + query : ""));
                    if (text != null)
                    {
                        statusJson = text;
                    }
                }
                finally
                {
                    Interlocked.Exchange(ref busy, 0);
                }
            });
        }

        private string Get(string url)
        {
            try
            {
                HttpWebRequest request = (HttpWebRequest)WebRequest.Create(url);
                request.Timeout = 1500;
                request.ReadWriteTimeout = 1500;
                request.Proxy = null;
                using (WebResponse response = request.GetResponse())
                using (StreamReader reader = new StreamReader(response.GetResponseStream()))
                {
                    string text = reader.ReadToEnd();
                    connected = true;
                    return text;
                }
            }
            catch (Exception)
            {
                connected = false;
                Interlocked.Exchange(ref nextSettingsTicks, 0);      // the code may have changed, read it again
                return null;
            }
        }

        private string BaseUrl()
        {
            if (DateTime.UtcNow.Ticks >= Interlocked.Read(ref nextSettingsTicks))
            {
                ReadSettings();
            }
            return "http://127.0.0.1:" + port + "/" + token + "/";
        }

        private void ReadSettings()
        {
            Interlocked.Exchange(ref nextSettingsTicks, DateTime.UtcNow.AddSeconds(30).Ticks);
            try
            {
                string path = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "SpeakerWeave", "settings.json");
                string text = File.ReadAllText(path);
                Match m = Regex.Match(text, "\"remote_port\"\\s*:\\s*(\\d+)");
                if (m.Success)
                {
                    port = int.Parse(m.Groups[1].Value);
                }
                m = Regex.Match(text, "\"remote_token\"\\s*:\\s*\"([0-9a-fA-F]+)\"");
                if (m.Success)
                {
                    token = m.Groups[1].Value;
                }
            }
            catch (Exception)
            {
            }
        }

        private double Number(string name)
        {
            double value;
            if (double.TryParse(Field(name), NumberStyles.Float, CultureInfo.InvariantCulture, out value))
            {
                return value;
            }
            return 0.0;
        }

        private string Field(string name)
        {
            Match m = Regex.Match(statusJson ?? "", "\"" + name + "\"\\s*:\\s*\"?([^\",}]*)");
            return m.Success ? m.Groups[1].Value : "";
        }
    }
}

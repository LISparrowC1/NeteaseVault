using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Windows.Forms;

namespace NeteaseVaultInstaller
{
    internal static class Program
    {
        [STAThread]
        private static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new InstallerForm());
        }
    }

    internal sealed class InstallerForm : Form
    {
        private readonly string _version;
        private readonly TextBox _path;
        private readonly Button _browse;
        private readonly Button _install;
        private readonly ProgressBar _progress;
        private readonly Label _status;
        private readonly CheckBox _launch;

        public InstallerForm()
        {
            _version = Assembly.GetExecutingAssembly().GetName().Version.ToString(3);
            Text = "NeteaseVault " + _version + " 绿色安装器";
            ClientSize = new Size(580, 250);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            Font = new Font("Microsoft YaHei UI", 9F);

            var title = new Label
            {
                Text = "NeteaseVault " + _version,
                Font = new Font(Font.FontFamily, 15F, FontStyle.Bold),
                AutoSize = true,
                Location = new Point(22, 18)
            };
            var note = new Label
            {
                Text = "选择安装目录。安装后整个目录可移动；删除目录即卸载。\n" +
                       "升级只覆盖程序文件，保留已有 music；data 由程序自行迁移。",
                AutoSize = true,
                ForeColor = Color.FromArgb(90, 96, 112),
                Location = new Point(24, 54)
            };

            var label = new Label { Text = "安装目录", AutoSize = true, Location = new Point(24, 104) };
            _path = new TextBox
            {
                Location = new Point(92, 100),
                Width = 370,
                Text = Path.Combine(Environment.CurrentDirectory, "NeteaseVault")
            };
            _browse = new Button { Text = "浏览…", Location = new Point(470, 98), Width = 86 };
            _browse.Click += BrowseClicked;

            _install = new Button
            {
                Text = "安装",
                Location = new Point(380, 198),
                Width = 86,
                Height = 30,
                BackColor = Color.FromArgb(46, 123, 231),
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat
            };
            _install.FlatAppearance.BorderSize = 0;
            _install.Click += InstallClicked;

            _progress = new ProgressBar
            {
                Location = new Point(24, 158),
                Width = 532,
                Height = 18,
                Style = ProgressBarStyle.Continuous
            };
            _status = new Label
            {
                Location = new Point(24, 180),
                Width = 330,
                AutoSize = false,
                Text = "准备安装",
                ForeColor = Color.FromArgb(90, 96, 112)
            };
            _launch = new CheckBox
            {
                Text = "安装完成后启动",
                Checked = true,
                AutoSize = true,
                Location = new Point(24, 205)
            };

            Controls.Add(title);
            Controls.Add(note);
            Controls.Add(label);
            Controls.Add(_path);
            Controls.Add(_browse);
            Controls.Add(_progress);
            Controls.Add(_status);
            Controls.Add(_launch);
            Controls.Add(_install);
        }

        private void BrowseClicked(object sender, EventArgs e)
        {
            using (var dialog = new FolderBrowserDialog())
            {
                dialog.Description = "选择 NeteaseVault 安装目录";
                dialog.SelectedPath = _path.Text;
                if (dialog.ShowDialog(this) == DialogResult.OK)
                {
                    _path.Text = Path.Combine(dialog.SelectedPath, "NeteaseVault");
                }
            }
        }

        private void InstallClicked(object sender, EventArgs e)
        {
            string target = _path.Text.Trim();
            if (target.Length == 0)
            {
                MessageBox.Show(this, "请选择安装目录。", "提示", MessageBoxButtons.OK, MessageBoxIcon.None);
                return;
            }
            try
            {
                target = Path.GetFullPath(target);
                string root = Path.GetPathRoot(target) ?? "";
                if (target.Length > root.Length)
                {
                    target = target.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                }
            }
            catch (Exception exc)
            {
                MessageBox.Show(this, "安装目录无效：" + exc.Message, "错误", MessageBoxButtons.OK, MessageBoxIcon.None);
                return;
            }
            if (File.Exists(Path.Combine(target, "NeteaseVault.exe")))
            {
                var answer = MessageBox.Show(
                    this,
                    "该目录已存在 NeteaseVault。\n\n将覆盖程序文件，保留 music 和 data 里的个人数据。继续吗？",
                    "升级安装", MessageBoxButtons.YesNo, MessageBoxIcon.None);
                if (answer != DialogResult.Yes)
                {
                    return;
                }
            }

            _install.Enabled = false;
            _browse.Enabled = false;
            _path.Enabled = false;
            _progress.Value = 0;
            _status.Text = "正在安装…";
            try
            {
                Directory.CreateDirectory(target);
                Directory.CreateDirectory(Path.Combine(target, "music"));
                Directory.CreateDirectory(Path.Combine(target, "data"));
                string legacyInternal = Path.Combine(target, "_internal");
                if (Directory.Exists(legacyInternal))
                {
                    try { Directory.Delete(legacyInternal, true); }
                    catch (IOException) { }
                    catch (UnauthorizedAccessException) { }
                }

                using (Stream stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))
                {
                    if (stream == null)
                    {
                        throw new InvalidOperationException("安装包缺少程序文件");
                    }
                    using (var archive = new ZipArchive(stream, ZipArchiveMode.Read))
                    {
                        int total = archive.Entries.Count;
                        int done = 0;
                        foreach (ZipArchiveEntry entry in archive.Entries)
                        {
                            string relative = entry.FullName.Replace('/', Path.DirectorySeparatorChar);
                            if (relative.StartsWith("music" + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
                            {
                                done++;
                                continue;
                            }
                            if (string.IsNullOrEmpty(entry.Name))
                            {
                                Directory.CreateDirectory(Path.Combine(target, relative));
                                continue;
                            }
                            string destination = Path.GetFullPath(Path.Combine(target, relative));
                            string prefix = target.EndsWith(Path.DirectorySeparatorChar.ToString())
                                ? target
                                : target + Path.DirectorySeparatorChar;
                            if (!destination.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                            {
                                throw new InvalidOperationException("安装包路径非法：" + relative);
                            }
                            Directory.CreateDirectory(Path.GetDirectoryName(destination));
                            entry.ExtractToFile(destination, true);
                            done++;
                            _progress.Value = Math.Min(100, (int)(done * 100L / Math.Max(1, total)));
                        }
                    }
                }
                _progress.Value = 100;
                _status.Text = "安装完成";
                if (_launch.Checked)
                {
                    string exe = Path.Combine(target, "NeteaseVault.exe");
                    if (File.Exists(exe))
                    {
                        Process.Start(new ProcessStartInfo(exe) { WorkingDirectory = target });
                    }
                }
                Close();
            }
            catch (Exception exc)
            {
                _status.Text = "安装失败";
                MessageBox.Show(this, "安装失败：" + exc.Message, "错误", MessageBoxButtons.OK, MessageBoxIcon.None);
                _install.Enabled = true;
                _browse.Enabled = true;
                _path.Enabled = true;
            }
        }
    }
}

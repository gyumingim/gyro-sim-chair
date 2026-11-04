"""Instructor voice: offline Windows SAPI text-to-speech (Korean voice "Microsoft Heami"), non-blocking.

A persistent PowerShell process reads one line per utterance from stdin; a new line cancels the one being spoken
(the newest instruction wins). No Korean voice / not Windows -> Voice.ok = False, text only.
    v = Voice(); v.say("오른손으로 스틱을 살짝 당기세요"); v.on = False   (mute)
"""
import os, re, subprocess, threading

PS = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -eq 'ko-KR' } | Select-Object -First 1
if ($v -eq $null) { [Console]::Out.WriteLine('NOVOICE'); exit 3 }
$s.SelectVoice($v.VoiceInfo.Name); $s.Rate = 1; $s.Volume = 100
[Console]::Out.WriteLine('VOICE ' + $v.VoiceInfo.Name); [Console]::Out.Flush()
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
while ($true) {
  $l = [Console]::In.ReadLine()
  if ($l -eq $null) { break }
  if ($l.StartsWith('#V ')) { $s.Volume = [int]$l.Substring(3); continue }
  if ($l.StartsWith('#R ')) { $s.Rate = [int]$l.Substring(3); continue }
  $s.SpeakAsyncCancelAll()
  if ($l.Length -gt 0) { $null = $s.SpeakAsync($l) }
}
"""

SPOKEN = [("↓", "아래 화살표"), ("↑", "위 화살표"), ("←", "왼쪽 화살표"), ("→", "오른쪽 화살표"), ("±", " 플러스 마이너스 "),
          ("°", "도"), (" ft", " 피트"), (" kt", " 노트"), (" fpm", " 피트 퍼 분"), ("%", " 퍼센트"), ("—", ","), ("·", ","), ("(", ","), (")", ",")]


def spoken(text):
    t = text
    for a, b in SPOKEN:
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t).strip()


class Voice:
    def __init__(self):
        self.on = True
        self.ok = False
        self.name = ""
        self.last = ""
        self.p = None
        if os.name != "nt":
            return
        try:
            self.p = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS], stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=0x08000000)   # no window
            line = self.p.stdout.readline().decode("utf-8", "ignore").strip()
            self.ok = line.startswith("VOICE")
            self.name = line[6:] if self.ok else ""
            print("sim: instructor voice", self.name if self.ok else "not available (no Korean SAPI voice) - text only", flush=True)
        except OSError as e:
            print("sim: instructor voice unavailable:", e, flush=True)
        self.lock = threading.Lock()

    def say(self, text):
        self.last = text
        if not (self.ok and self.on and self.p and self.p.poll() is None):
            return False
        try:
            with self.lock:
                self.p.stdin.write((spoken(text) + "\n").encode("utf-8"))
                self.p.stdin.flush()
            return True
        except OSError:
            self.ok = False
            return False

    def _write(self, line):
        if not (self.ok and self.p and self.p.poll() is None):
            return False
        try:
            with self.lock:
                self.p.stdin.write((line + chr(10)).encode("utf-8"))
                self.p.stdin.flush()
            return True
        except OSError:
            self.ok = False
            return False

    def set_params(self, volume=90, rate=0):
        """volume 0..100, rate -10..10 (SAPI)."""
        self._write("#V %d" % max(0, min(100, int(volume))))
        self._write("#R %d" % max(-10, min(10, int(rate))))

    def say_now(self, text):
        """speak (or cancel with "") regardless of the mute switch."""
        return self._write(spoken(text))

    def stop(self):
        self.say("") if self.ok else None

    def toggle(self):
        self.on = not self.on
        if not self.on and self.ok and self.p:
            try:
                self.p.stdin.write(b"\n")
                self.p.stdin.flush()
            except OSError:
                pass
        return self.on

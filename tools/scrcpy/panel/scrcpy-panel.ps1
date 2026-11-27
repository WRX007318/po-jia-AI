$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$script:root = Split-Path -Parent $MyInvocation.MyCommand.Path
$script:adb = Join-Path $script:root 'adb.exe'
$script:scrcpy = Join-Path $script:root 'scrcpy.exe'
$script:activeMirrors = [System.Collections.Generic.List[System.Diagnostics.Process]]::new()

if (-not (Test-Path -LiteralPath $script:adb) -or -not (Test-Path -LiteralPath $script:scrcpy)) {
    [System.Windows.Forms.MessageBox]::Show('未找到 scrcpy 或 adb。请重新运行仓库中的安装脚本。', 'scrcpy 功能面板', 'OK', 'Error') | Out-Null
    exit 1
}

$form = New-Object System.Windows.Forms.Form
$form.Text = 'scrcpy 安卓投屏面板'
$form.StartPosition = 'CenterScreen'
$form.ClientSize = New-Object System.Drawing.Size(600, 480)
$form.MinimumSize = New-Object System.Drawing.Size(616, 519)
$form.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 9)

$title = New-Object System.Windows.Forms.Label
$title.Text = '安卓投屏控制台'
$title.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 18, [System.Drawing.FontStyle]::Bold)
$title.Location = New-Object System.Drawing.Point(22, 18)
$title.Size = New-Object System.Drawing.Size(350, 38)
$form.Controls.Add($title)

$status = New-Object System.Windows.Forms.Label
$status.Text = '正在读取设备…'
$status.AutoEllipsis = $true
$status.ForeColor = [System.Drawing.Color]::FromArgb(80, 90, 105)
$status.Location = New-Object System.Drawing.Point(25, 60)
$status.Size = New-Object System.Drawing.Size(500, 24)
$form.Controls.Add($status)

$deviceLabel = New-Object System.Windows.Forms.Label
$deviceLabel.Text = '已连接设备'
$deviceLabel.Location = New-Object System.Drawing.Point(26, 104)
$deviceLabel.Size = New-Object System.Drawing.Size(100, 25)
$form.Controls.Add($deviceLabel)

$devices = New-Object System.Windows.Forms.ComboBox
$devices.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDownList
$devices.DisplayMember = 'Text'
$devices.Location = New-Object System.Drawing.Point(130, 100)
$devices.Size = New-Object System.Drawing.Size(300, 28)
$form.Controls.Add($devices)

$refresh = New-Object System.Windows.Forms.Button
$refresh.Text = '刷新'
$refresh.Location = New-Object System.Drawing.Point(442, 98)
$refresh.Size = New-Object System.Drawing.Size(88, 32)
$form.Controls.Add($refresh)

$sizeGroup = New-Object System.Windows.Forms.GroupBox
$sizeGroup.Text = '窗口尺寸与画质'
$sizeGroup.Location = New-Object System.Drawing.Point(24, 140)
$sizeGroup.Size = New-Object System.Drawing.Size(552, 124)
$form.Controls.Add($sizeGroup)

$sizeLabel = New-Object System.Windows.Forms.Label
$sizeLabel.Text = '窗口大小'
$sizeLabel.Location = New-Object System.Drawing.Point(14, 29)
$sizeLabel.Size = New-Object System.Drawing.Size(72, 24)
$sizeGroup.Controls.Add($sizeLabel)

$sizeMode = New-Object System.Windows.Forms.ComboBox
$sizeMode.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDownList
[void]$sizeMode.Items.AddRange(@('适配屏幕', '小窗 420×900', '标准 540×1160', '大窗 720×1540', '自定义'))
$sizeMode.SelectedIndex = 0
$sizeMode.Location = New-Object System.Drawing.Point(88, 25)
$sizeMode.Size = New-Object System.Drawing.Size(166, 28)
$sizeGroup.Controls.Add($sizeMode)

$widthLabel = New-Object System.Windows.Forms.Label
$widthLabel.Text = '宽'
$widthLabel.Location = New-Object System.Drawing.Point(267, 29)
$widthLabel.Size = New-Object System.Drawing.Size(24, 22)
$sizeGroup.Controls.Add($widthLabel)

$widthValue = New-Object System.Windows.Forms.NumericUpDown
$widthValue.Minimum = 240
$widthValue.Maximum = 2400
$widthValue.Increment = 40
$widthValue.Value = 540
$widthValue.Location = New-Object System.Drawing.Point(292, 25)
$widthValue.Size = New-Object System.Drawing.Size(76, 28)
$widthValue.Enabled = $false
$sizeGroup.Controls.Add($widthValue)

$heightLabel = New-Object System.Windows.Forms.Label
$heightLabel.Text = '高'
$heightLabel.Location = New-Object System.Drawing.Point(380, 29)
$heightLabel.Size = New-Object System.Drawing.Size(24, 22)
$sizeGroup.Controls.Add($heightLabel)

$heightValue = New-Object System.Windows.Forms.NumericUpDown
$heightValue.Minimum = 320
$heightValue.Maximum = 3000
$heightValue.Increment = 40
$heightValue.Value = 1160
$heightValue.Location = New-Object System.Drawing.Point(405, 25)
$heightValue.Size = New-Object System.Drawing.Size(82, 28)
$heightValue.Enabled = $false
$sizeGroup.Controls.Add($heightValue)

$keepRatio = New-Object System.Windows.Forms.CheckBox
$keepRatio.Text = '保持手机画面比例'
$keepRatio.Checked = $true
$keepRatio.Location = New-Object System.Drawing.Point(14, 61)
$keepRatio.Size = New-Object System.Drawing.Size(175, 24)
$sizeGroup.Controls.Add($keepRatio)

$qualityLabel = New-Object System.Windows.Forms.Label
$qualityLabel.Text = '清晰度上限'
$qualityLabel.Location = New-Object System.Drawing.Point(206, 63)
$qualityLabel.Size = New-Object System.Drawing.Size(82, 22)
$sizeGroup.Controls.Add($qualityLabel)

$qualityMode = New-Object System.Windows.Forms.ComboBox
$qualityMode.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDownList
[void]$qualityMode.Items.AddRange(@('原始分辨率', '1080p', '720p'))
$qualityMode.SelectedIndex = 0
$qualityMode.Location = New-Object System.Drawing.Point(292, 59)
$qualityMode.Size = New-Object System.Drawing.Size(195, 28)
$sizeGroup.Controls.Add($qualityMode)

$fullscreen = New-Object System.Windows.Forms.CheckBox
$fullscreen.Text = '全屏启动（忽略窗口大小）'
$fullscreen.Checked = $false
$fullscreen.Location = New-Object System.Drawing.Point(14, 91)
$fullscreen.Size = New-Object System.Drawing.Size(240, 24)
$sizeGroup.Controls.Add($fullscreen)

$sizeMode.Add_SelectedIndexChanged({
    $custom = ($sizeMode.SelectedIndex -eq 4)
    $widthValue.Enabled = $custom
    $heightValue.Enabled = $custom
})

$usbButton = New-Object System.Windows.Forms.Button
$usbButton.Text = 'USB 投屏'
$usbButton.Location = New-Object System.Drawing.Point(26, 278)
$usbButton.Size = New-Object System.Drawing.Size(150, 44)
$usbButton.BackColor = [System.Drawing.Color]::FromArgb(35, 112, 215)
$usbButton.ForeColor = [System.Drawing.Color]::White
$usbButton.FlatStyle = 'Flat'
$form.Controls.Add($usbButton)

$recordButton = New-Object System.Windows.Forms.Button
$recordButton.Text = '开始录屏'
$recordButton.Location = New-Object System.Drawing.Point(192, 278)
$recordButton.Size = New-Object System.Drawing.Size(150, 44)
$form.Controls.Add($recordButton)

$shotButton = New-Object System.Windows.Forms.Button
$shotButton.Text = '保存截图'
$shotButton.Location = New-Object System.Drawing.Point(358, 278)
$shotButton.Size = New-Object System.Drawing.Size(150, 44)
$form.Controls.Add($shotButton)

$wirelessLabel = New-Object System.Windows.Forms.Label
$wirelessLabel.Text = '无线连接 IP'
$wirelessLabel.Location = New-Object System.Drawing.Point(26, 350)
$wirelessLabel.Size = New-Object System.Drawing.Size(100, 25)
$form.Controls.Add($wirelessLabel)

$ipBox = New-Object System.Windows.Forms.TextBox
$ipBox.Text = '192.168.1.100'
$ipBox.Location = New-Object System.Drawing.Point(130, 346)
$ipBox.Size = New-Object System.Drawing.Size(190, 28)
$form.Controls.Add($ipBox)

$wirelessButton = New-Object System.Windows.Forms.Button
$wirelessButton.Text = '连接并投屏'
$wirelessButton.Location = New-Object System.Drawing.Point(330, 343)
$wirelessButton.Size = New-Object System.Drawing.Size(178, 34)
$form.Controls.Add($wirelessButton)

$hint = New-Object System.Windows.Forms.Label
$hint.Text = '无线首次连接：先用 USB 连接手机并开启 USB 调试；点击无线连接后，按提示切换到手机的 IP 地址。'
$hint.ForeColor = [System.Drawing.Color]::FromArgb(100, 108, 120)
$hint.Location = New-Object System.Drawing.Point(27, 399)
$hint.Size = New-Object System.Drawing.Size(530, 48)
$form.Controls.Add($hint)

function Get-SelectedSerial {
    if ($devices.SelectedItem) { return [string]$devices.SelectedItem.Tag }
    return $null
}

function Refresh-Devices {
    $selected = Get-SelectedSerial
    $devices.Items.Clear()
    $lines = @(& $script:adb devices -l 2>&1)
    foreach ($line in $lines) {
        $value = [string]$line
        if ($value -match '^([^\s]+)\s+(device|unauthorized|offline)(?:\s+(.*))?$') {
            $serial = $Matches[1]
            $state = $Matches[2]
            $details = $Matches[3]
            $model = if ($details -match 'model:([^\s]+)') { $Matches[1].Replace('_', ' ') } else { $serial }
            $entry = [pscustomobject]@{ Text = "$model  [$state]"; Tag = $serial }
            [void]$devices.Items.Add($entry)
            if ($serial -eq $selected) { $devices.SelectedItem = $entry }
        }
    }
    if ($devices.Items.Count -gt 0 -and $devices.SelectedIndex -lt 0) { $devices.SelectedIndex = 0 }
    $ready = @($devices.Items | Where-Object { $_.Text -match '\[device\]$' }).Count
    if ($ready -gt 0) { $status.Text = "$ready 台设备已授权并就绪。"; $status.ForeColor = [System.Drawing.Color]::FromArgb(35, 135, 80) }
    elseif ($devices.Items.Count -gt 0) { $status.Text = '检测到设备，请解锁手机并确认 USB 调试授权。'; $status.ForeColor = [System.Drawing.Color]::FromArgb(190, 120, 20) }
    else { $status.Text = '未检测到设备。连接 USB 并开启手机的 USB 调试后点“刷新”。'; $status.ForeColor = [System.Drawing.Color]::FromArgb(100, 108, 120) }
}

function Start-Mirror([string]$Serial, [switch]$Record) {
    if (-not $Serial) { [System.Windows.Forms.MessageBox]::Show('请先连接并选择一台设备。', 'scrcpy', 'OK', 'Information') | Out-Null; return }
    $scrcpyArgs = @('--serial', $Serial)
    $workArea = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
    switch ($sizeMode.SelectedIndex) {
        0 {
            $targetHeight = [Math]::Min(1200, [int]($workArea.Height * 0.86))
            $targetWidth = [int]($targetHeight * 0.48)
            if ($targetWidth -gt [int]($workArea.Width * 0.82)) {
                $targetWidth = [int]($workArea.Width * 0.82)
                $targetHeight = [int]($targetWidth / 0.48)
            }
        }
        1 { $targetWidth = 420; $targetHeight = 900 }
        2 { $targetWidth = 540; $targetHeight = 1160 }
        3 { $targetWidth = 720; $targetHeight = 1540 }
        4 { $targetWidth = [int]$widthValue.Value; $targetHeight = [int]$heightValue.Value }
    }
    $scrcpyArgs += @('--window-width', [string]$targetWidth, '--window-height', [string]$targetHeight)
    if (-not $keepRatio.Checked) { $scrcpyArgs += '--no-window-aspect-ratio-lock' }
    switch ($qualityMode.SelectedIndex) {
        1 { $scrcpyArgs += @('--max-size', '1920') }
        2 { $scrcpyArgs += @('--max-size', '1280') }
    }
    if ($fullscreen.Checked) { $scrcpyArgs += '--fullscreen' }
    if ($Record) {
        $videoDir = [Environment]::GetFolderPath('MyVideos')
        $file = Join-Path $videoDir ("scrcpy-{0}.mp4" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
        $scrcpyArgs += @('--record', $file)
        $status.Text = "录屏正在写入：$file（关闭投屏窗口结束录制）"
    }
    $quoted = ($scrcpyArgs | ForEach-Object { '"' + ([string]$_).Replace('"', '\"') + '"' }) -join ' '
    $proc = Start-Process -FilePath $script:scrcpy -ArgumentList $quoted -WorkingDirectory $script:root -PassThru
    [void]$script:activeMirrors.Add($proc)
}

$refresh.Add_Click({ Refresh-Devices })
$usbButton.Add_Click({ Start-Mirror (Get-SelectedSerial) })
$recordButton.Add_Click({ Start-Mirror (Get-SelectedSerial) -Record })
$shotButton.Add_Click({
    $serial = Get-SelectedSerial
    if (-not $serial) { [System.Windows.Forms.MessageBox]::Show('请先连接并选择一台设备。', 'scrcpy', 'OK', 'Information') | Out-Null; return }
    $pictures = [Environment]::GetFolderPath('MyPictures')
    $file = Join-Path $pictures ("scrcpy-{0}.png" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
    $remote = '/sdcard/Pictures/scrcpy-panel-' + [guid]::NewGuid().ToString('N') + '.png'
    & $script:adb -s $serial shell screencap -p $remote | Out-Null
    if ($LASTEXITCODE -ne 0) { [System.Windows.Forms.MessageBox]::Show('截图失败，请确认设备已授权。', 'scrcpy', 'OK', 'Error') | Out-Null; return }
    & $script:adb -s $serial pull $remote $file | Out-Null
    & $script:adb -s $serial shell rm $remote | Out-Null
    if (Test-Path -LiteralPath $file) {
        $status.Text = "截图已保存：$file"
        [System.Windows.Forms.MessageBox]::Show("截图已保存到：`n$file", 'scrcpy', 'OK', 'Information') | Out-Null
    } else { [System.Windows.Forms.MessageBox]::Show('截图保存失败。', 'scrcpy', 'OK', 'Error') | Out-Null }
})
$wirelessButton.Add_Click({
    $ip = $ipBox.Text.Trim()
    if ($ip -notmatch '^(?:\d{1,3}\.){3}\d{1,3}$') { [System.Windows.Forms.MessageBox]::Show('请输入手机的 IPv4 地址。', '无线连接', 'OK', 'Warning') | Out-Null; return }
    $serial = Get-SelectedSerial
    if ($serial -and $serial -notmatch ':') {
        & $script:adb -s $serial tcpip 5555 | Out-Null
        if ($LASTEXITCODE -ne 0) { [System.Windows.Forms.MessageBox]::Show('无法开启无线调试。请确认手机已通过 USB 连接并授权。', '无线连接', 'OK', 'Error') | Out-Null; return }
        Start-Sleep -Seconds 2
    }
    $endpoint = "$ip`:5555"
    & $script:adb connect $endpoint | Out-Null
    if ($LASTEXITCODE -ne 0) { [System.Windows.Forms.MessageBox]::Show('无线连接失败。确认手机和电脑在同一 Wi-Fi，并填写手机的 IP 地址。', '无线连接', 'OK', 'Error') | Out-Null; return }
    Refresh-Devices
    for ($i = 0; $i -lt $devices.Items.Count; $i++) { if ($devices.Items[$i].Tag -eq $endpoint) { $devices.SelectedIndex = $i; break } }
    Start-Mirror $endpoint
})

$form.Add_Shown({ Refresh-Devices })
[void]$form.ShowDialog()

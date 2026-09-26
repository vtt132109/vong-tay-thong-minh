$port = New-Object System.IO.Ports.SerialPort "COM11", 115200
$port.ReadTimeout = 2000
try {
    $port.Open()
    Write-Host "[+] Connected to COM11. Listening for 5 seconds..."
    $timeout = [System.DateTime]::Now.AddSeconds(5)
    while ([System.DateTime]::Now -lt $timeout) {
        try {
            $line = $port.ReadLine()
            Write-Host $line
        } catch [System.TimeoutException] {
            # continue
        }
    }
} catch {
    Write-Host "Error opening COM5: $_"
} finally {
    if ($port.IsOpen) {
        $port.Close()
    }
}

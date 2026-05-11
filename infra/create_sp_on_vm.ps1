Write-Output "Creating usp_update_watermark stored procedure in RetailDB..."

$sql = @"
USE RetailDB;

IF OBJECT_ID('dbo.usp_update_watermark', 'P') IS NOT NULL
    DROP PROCEDURE dbo.usp_update_watermark;

EXEC('
CREATE PROCEDURE dbo.usp_update_watermark
    @pipeline_name       NVARCHAR(100),
    @new_watermark_value DATETIME2
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE dbo.pipeline_watermarks
    SET    last_watermark_value = @new_watermark_value
    WHERE  pipeline_name = @pipeline_name;

    IF @@ROWCOUNT = 0
    BEGIN
        INSERT INTO dbo.pipeline_watermarks (pipeline_name, last_watermark_value)
        VALUES (@pipeline_name, @new_watermark_value);
    END
END
');
"@

try {
    $conn = New-Object System.Data.SqlClient.SqlConnection("Server=localhost;Database=master;User Id=sa;Password=RetailLH@2026!;TrustServerCertificate=True;")
    $conn.Open()

    # Ensure RetailDB exists
    $cmd = New-Object System.Data.SqlClient.SqlCommand("IF NOT EXISTS (SELECT name FROM sys.databases WHERE name='RetailDB') CREATE DATABASE RetailDB;", $conn)
    $cmd.ExecuteNonQuery() | Out-Null
    $conn.Close()

    # Now connect to RetailDB
    $connDB = New-Object System.Data.SqlClient.SqlConnection("Server=localhost;Database=RetailDB;User Id=sa;Password=RetailLH@2026!;TrustServerCertificate=True;")
    $connDB.Open()

    # Drop and recreate SP
    $dropSP = New-Object System.Data.SqlClient.SqlCommand("IF OBJECT_ID('dbo.usp_update_watermark', 'P') IS NOT NULL DROP PROCEDURE dbo.usp_update_watermark;", $connDB)
    $dropSP.ExecuteNonQuery() | Out-Null

    $createSP = New-Object System.Data.SqlClient.SqlCommand(@"
CREATE PROCEDURE dbo.usp_update_watermark
    @pipeline_name       NVARCHAR(100),
    @new_watermark_value DATETIME2
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE dbo.pipeline_watermarks
    SET    last_watermark_value = @new_watermark_value
    WHERE  pipeline_name = @pipeline_name;
    IF @@ROWCOUNT = 0
    BEGIN
        INSERT INTO dbo.pipeline_watermarks (pipeline_name, last_watermark_value)
        VALUES (@pipeline_name, @new_watermark_value);
    END
END
"@, $connDB)
    $createSP.ExecuteNonQuery() | Out-Null

    Write-Output "Stored procedure usp_update_watermark created successfully."

    # Verify
    $verify = New-Object System.Data.SqlClient.SqlCommand("SELECT name, type_desc FROM sys.objects WHERE name = 'usp_update_watermark';", $connDB)
    $reader = $verify.ExecuteReader()
    while ($reader.Read()) {
        Write-Output "Verified: $($reader['name']) ($($reader['type_desc']))"
    }
    $connDB.Close()
} catch {
    Write-Output "ERROR: $($_.Exception.Message)"
    exit 1
}

Write-Output "Done."

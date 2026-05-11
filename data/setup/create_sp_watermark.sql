-- ============================================================
-- Stored procedure: dbo.usp_update_watermark
-- Called by ADF after a successful incremental copy to advance
-- the high-watermark to the max value seen in this pipeline run.
-- ============================================================

USE RetailDB;
GO

IF OBJECT_ID('dbo.usp_update_watermark', 'P') IS NOT NULL
    DROP PROCEDURE dbo.usp_update_watermark;
GO

CREATE PROCEDURE dbo.usp_update_watermark
    @pipeline_name       NVARCHAR(100),
    @new_watermark_value DATETIME2
AS
BEGIN
    SET NOCOUNT ON;

    UPDATE dbo.pipeline_watermarks
    SET    last_watermark_value = @new_watermark_value
    WHERE  pipeline_name = @pipeline_name;

    -- Safety: insert if the row somehow doesn't exist
    IF @@ROWCOUNT = 0
    BEGIN
        INSERT INTO dbo.pipeline_watermarks (pipeline_name, last_watermark_value)
        VALUES (@pipeline_name, @new_watermark_value);
    END
END;
GO

-- Verify
SELECT * FROM dbo.pipeline_watermarks;
GO

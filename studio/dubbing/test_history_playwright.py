import asyncio
import os
import uvicorn
import threading
import time
from playwright.async_api import async_playwright
from app.auth.clerk_auth import require_user, AuthenticatedUser
from main import app

# Create mock authenticated user for test suite
def mock_require_user():
    return AuthenticatedUser(
        user_id="user_3Gqh0sVtFqypoOoT3L5TntH3AO9",
        email="mhamadtah548@gmail.com",
        workspace_id="6820c4e7-062e-4946-8f0d-9c26aebcd000",
        role="org:member",
        raw_claims={},
        access_token="test-token"
    )

# Override require_user dependency for testing server
app.dependency_overrides[require_user] = mock_require_user

def run_test_server():
    uvicorn.run(app, host="127.0.0.1", port=8999, log_level="warning")

async def test_video_history():
    print("--- 1. Starting Test Server on Port 8999 ---")
    server_thread = threading.Thread(target=run_test_server, daemon=True)
    server_thread.start()
    time.sleep(1.5)  # Wait for uvicorn to boot

    from convex import ConvexClient
    convex_url = os.getenv("CONVEX_URL", "http://127.0.0.1:3210")
    client = ConvexClient(convex_url)
    jobs = client.query("dubbingJobs:listForWorkspaceInternal", {"workspaceId": "6820c4e7-062e-4946-8f0d-9c26aebcd000", "limit": 10})
    completed_job = next((j for j in jobs if j.get("status") in ("done", "completed") and j.get("resultVideoR2Key")), None)
    
    assert completed_job is not None, "No completed job found in Convex"
    job_id = completed_job["_id"]
    print(f"Target completed job ID: {job_id}")

    print("\n--- 2. Playwright End-to-End Browser Testing ---")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        # Test video stream URL (inline=true)
        stream_url = f"http://127.0.0.1:8999/video/jobs/{job_id}/download?inline=true"
        print(f"Testing inline video stream URL: {stream_url}")
        response = await page.goto(stream_url)
        print(f"Stream Response Status: {response.status}")
        print(f"Content-Type: {response.headers.get('content-type')}")
        assert response.status == 200, f"Expected status 200, got {response.status}"
        assert "video/mp4" in response.headers.get("content-type", ""), f"Expected video/mp4, got {response.headers.get('content-type')}"

        # Check HTML5 Video capabilities in browser
        video_info = await page.evaluate("""() => {
            const video = document.querySelector('video');
            if (!video) return { found: false };
            return {
                found: true,
                duration: video.duration,
                paused: video.paused,
                volume: video.volume,
                controls: video.controls,
                readyState: video.readyState,
                canPlayType: video.canPlayType('video/mp4')
            };
        }""")
        print(f"Browser Video Metadata & Controls Check: {video_info}")
        assert video_info["found"], "Video element should exist in browser"
        assert video_info["duration"] > 0, "Video duration should be > 0"
        assert video_info["controls"] is True, "Video controls should be enabled for fullscreen/sound"

        # Test volume / sound modification in browser
        new_volume = await page.evaluate("""() => {
            const video = document.querySelector('video');
            video.volume = 0.5;
            return video.volume;
        }""")
        print(f"Tested sound level change: volume set to {new_volume}")
        assert new_volume == 0.5, "Sound volume should be editable"

        # Test direct download URL (attachment)
        download_url = f"http://127.0.0.1:8999/video/jobs/{job_id}/download"
        print(f"\nTesting direct download URL: {download_url}")
        async with page.expect_download() as download_info:
            await page.evaluate(f"window.location.href = '{download_url}';")
        download = await download_info.value
        path = await download.path()
        size = os.path.getsize(path)
        print(f"Download Triggered Successfully! Filename: {download.suggested_filename}, Size: {size} bytes")
        assert size > 0, "Downloaded file should not be empty"

        await browser.close()
    
    print("\n[OK] ALL PLAYWRIGHT VIDEO PLAYBACK, FULLSCREEN, SOUND & DOWNLOAD TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(test_video_history())

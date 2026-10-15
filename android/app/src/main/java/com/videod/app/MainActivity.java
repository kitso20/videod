package com.videod.app;

import android.app.Activity;
import android.app.DownloadManager;
import android.content.Context;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.webkit.DownloadListener;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.widget.Toast;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

public class MainActivity extends Activity {

    private static final int PORT = 8765;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        if (Build.VERSION.SDK_INT < 29
                && checkSelfPermission(android.Manifest.permission.WRITE_EXTERNAL_STORAGE)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(
                    new String[]{android.Manifest.permission.WRITE_EXTERNAL_STORAGE}, 1);
        }

        if (!Python.isStarted()) {
            Python.start(new AndroidPlatform(this));
        }
        Python.getInstance().getModule("server").callAttr("start", PORT);

        WebView web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(false);
        s.setMediaPlaybackRequiresUserGesture(false);

        web.setDownloadListener(new DownloadListener() {
            @Override
            public void onDownloadStart(String url, String userAgent, String contentDisposition,
                                        String mimeType, long contentLength) {
                saveViaDownloadManager(url, mimeType);
            }
        });

        setContentView(web);
        web.loadUrl("http://127.0.0.1:" + PORT + "/");
    }

    private void saveViaDownloadManager(String url, String mimeType) {
        try {
            String name = fileName(url);
            DownloadManager.Request req = new DownloadManager.Request(Uri.parse(url));
            req.setMimeType(mimeType != null && !mimeType.isEmpty()
                    ? mimeType : "application/octet-stream");
            req.setTitle(name);
            req.setNotificationVisibility(
                    DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
            req.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name);
            DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
            dm.enqueue(req);
            Toast.makeText(this, "Downloading " + name, Toast.LENGTH_SHORT).show();
        } catch (Exception e) {
            Toast.makeText(this, "Download failed: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    private String fileName(String url) {
        try {
            String seg = Uri.parse(url).getLastPathSegment();
            if (seg != null && !seg.isEmpty()) {
                return seg.replace('/', '_');
            }
        } catch (Exception ignored) {
        }
        return "video";
    }
}

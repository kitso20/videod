package com.videod.app;

import android.app.Activity;
import android.content.ContentValues;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.MediaStore;
import android.text.TextUtils;
import android.webkit.DownloadListener;
import android.webkit.JavascriptInterface;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.widget.Toast;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;

public class MainActivity extends Activity {

    private static final int PORT = 8765;
    private WebView web;
    private final Handler ui = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        if (Build.VERSION.SDK_INT < 29
                && checkSelfPermission(android.Manifest.permission.WRITE_EXTERNAL_STORAGE)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(
                    new String[]{android.Manifest.permission.WRITE_EXTERNAL_STORAGE}, 1);
        }

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(false);
        s.setMediaPlaybackRequiresUserGesture(false);
        web.addJavascriptInterface(new Bridge(), "AndroidBridge");
        web.setDownloadListener(new DownloadListener() {
            @Override
            public void onDownloadStart(String url, String userAgent, String contentDisposition,
                                        String mimeType, long contentLength) {
                Uri u = Uri.parse(url);
                String name = u.getLastPathSegment();
                String cid = u.getQueryParameter("cid");
                if (name != null) {
                    saveFile(name, cid == null ? "" : cid);
                }
            }
        });
        setContentView(web);

        try {
            if (!Python.isStarted()) {
                Python.start(new AndroidPlatform(this));
            }
            Python.getInstance().getModule("server").callAttr("start", PORT);
            web.loadUrl("http://127.0.0.1:" + PORT + "/");
        } catch (Throwable t) {
            showError(t);
        }
    }

    private void showError(Throwable t) {
        StringWriter sw = new StringWriter();
        t.printStackTrace(new PrintWriter(sw));
        String abi = Build.SUPPORTED_ABIS.length > 0 ? Build.SUPPORTED_ABIS[0] : "?";
        String html = "<html><body style='font-family:monospace;font-size:13px;padding:12px'>"
                + "<h3>viDeoD failed to start</h3>"
                + "<b>Android:</b> " + Build.VERSION.RELEASE + " (SDK " + Build.VERSION.SDK_INT + ")<br>"
                + "<b>Device:</b> " + Build.MANUFACTURER + " " + Build.MODEL + "<br>"
                + "<b>Primary ABI:</b> " + abi + "<br>"
                + "<b>All ABIs:</b> " + TextUtils.join(", ", Build.SUPPORTED_ABIS)
                + "<pre style='white-space:pre-wrap'>"
                + TextUtils.htmlEncode(sw.toString())
                + "</pre></body></html>";
        web.loadDataWithBaseURL(null, html, "text/html", "utf-8", null);
    }

    /** Called from the web page (see app.js) once a download finishes. */
    private class Bridge {
        @JavascriptInterface
        public void save(final String filename, final String cid) {
            saveFile(filename, cid);
        }
    }

    private void saveFile(final String filename, final String cid) {
        new Thread(() -> fetchAndSave(filename, cid)).start();
    }

    private void fetchAndSave(String filename, String cid) {
        HttpURLConnection conn = null;
        Uri mediaUri = null;
        ContentValues pending = null;
        boolean saved = false;
        try {
            String url = "http://127.0.0.1:" + PORT + "/api/files/"
                    + URLEncoder.encode(filename, "UTF-8").replace("+", "%20")
                    + "?cid=" + URLEncoder.encode(cid == null ? "" : cid, "UTF-8");
            conn = (HttpURLConnection) new URL(url).openConnection();
            conn.setConnectTimeout(15000);
            conn.setReadTimeout(300000);
            int code = conn.getResponseCode();
            if (code != 200) {
                toast("Download failed (HTTP " + code + ")");
                return;
            }
            String mime = conn.getContentType();
            if (mime == null || mime.isEmpty()) mime = "application/octet-stream";

            InputStream in = conn.getInputStream();
            OutputStream out;
            if (Build.VERSION.SDK_INT >= 29) {
                pending = new ContentValues();
                pending.put(MediaStore.Downloads.DISPLAY_NAME, filename);
                pending.put(MediaStore.Downloads.MIME_TYPE, mime);
                pending.put(MediaStore.Downloads.IS_PENDING, 1);
                mediaUri = getContentResolver()
                        .insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, pending);
                if (mediaUri == null) {
                    in.close();
                    toast("Could not create file in Downloads");
                    return;
                }
                out = getContentResolver().openOutputStream(mediaUri);
            } else {
                File dir = Environment
                        .getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);
                if (!dir.exists()) dir.mkdirs();
                out = new FileOutputStream(new File(dir, filename));
            }
            if (out == null) {
                in.close();
                toast("Could not open output file in Downloads");
                return;
            }

            byte[] buf = new byte[64 * 1024];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            out.flush();
            out.close();
            in.close();

            if (mediaUri != null && pending != null) {
                pending.clear();
                pending.put(MediaStore.Downloads.IS_PENDING, 0);
                getContentResolver().update(mediaUri, pending, null, null);
            }
            saved = true;
            toast("Saved to Downloads: " + filename);
        } catch (Exception e) {
            toast("Download failed: " + e.getMessage());
        } finally {
            if (!saved && mediaUri != null) {
                try {
                    getContentResolver().delete(mediaUri, null, null);
                } catch (Exception ignored) {
                    // best effort cleanup of the pending MediaStore row
                }
            }
            if (conn != null) conn.disconnect();
        }
    }

    private void toast(final String msg) {
        ui.post(() -> Toast.makeText(MainActivity.this, msg, Toast.LENGTH_LONG).show());
    }
}

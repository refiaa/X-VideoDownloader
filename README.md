# X(Twitter) Video Downloader

> [!WARNING]
> このスクリプトの実行により発生するあらゆる問題に対して作者は責任を負いません。X(Twitter)の利用規約を遵守し、自己責任でご利用ください。

特定のX(Twitter)アカウントの動画を自動ダウンロードするスクリプトです。

## ファイル構造

```
│  .env
│  .gitignore
│  LICENSE
│  README.md
│  
├─output
│      .gitkeep
│
├─src
│      downloader.py
│      getId.py
│      __init__.py
│      x.com_cookies.txt
│
└─videos
        .gitkeep
```

## 必要なもの

- Python 3.7+
- Chrome Browser
- ffmpeg
- [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc?hl=ja)

## セットアップ

### 1. 環境変数設定

`.env`ファイルを作成し以下を設定：

```env
# Twitter認証（自動ログイン用）
TWITTER_USERNAME=your_username
TWITTER_PASSWORD=your_password

# ダウンロード対象
TARGET_USERNAME=target_account_id

# ディレクトリ設定
OUTPUT_DIR=output
VIDEOS_DIR=videos

# スクレイピング設定
TIMEOUT=30
SCROLL_PAUSE_TIME=3.0
MAX_SCROLLS=300
HEADLESS=False
WAIT_AFTER_LOAD=10.0
SCROLL_INCREMENT=800
MAX_CONSECUTIVE_NO_NEW_CONTENT=15
```

### 3. クッキーファイル設定

1. [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc?hl=ja)をインストール
2. X.comでログイン後、拡張機能でクッキーをエクスポート
3. `x.com_cookies.txt`として保存

## 実行手順

### 1. メディアURL取得

- `getId.py`を実行
- 対象アカウントのメディア付き投稿URLを収集
- `output/`に`{username}_media_posts_full_{timestamp}.csv`が生成される

### 2. 動画ダウンロード

- `Downloader.py`を実行
- 収集したURLから動画をダウンロード
- `videos/{username}/`に`{post_id}.mp4`として保存される

## トラブルシューティング

### よくあるエラー

**ログインエラー**
- 環境変数の認証情報を確認
- 2FA有効アカウントは手動ログインを使用

**レート制限エラー**
```
WARNING: [twitter] Rate-limit exceeded; falling back to syndication endpoint
WARNING: [twitter] 13240971234234124: Not all metadata or media is available via syndication endpoint
ERROR: [twitter] 13240971234234124: No video could be found in this tweet
```
- Twitterのレート制限
- 時間をおいて再実行

**ffmpegエラー**
- ffmpegがPATHに追加されているか確認
- [ffmpeg公式サイト](https://ffmpeg.org/download.html)からダウンロード

## 注意事項

- 利用規約を遵守してください
- 過度なリクエストは避けてください
- 個人利用の範囲内でご使用ください

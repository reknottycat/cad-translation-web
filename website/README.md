# CAD Translation System 宣传站

这是项目的独立静态宣传页。页面不依赖后端、Node.js 或第三方 CDN，可直接由
GitHub Pages 托管。

## 本地预览

在仓库根目录运行：

```powershell
python -m http.server 4173 --directory website
```

然后访问 `http://127.0.0.1:4173/`。

## GitHub Pages 部署

`.github/workflows/deploy-pages.yml` 会在 `main` 分支的 `website/` 内容发生变化时
自动发布，也可以在 GitHub Actions 页面手动触发。首次使用时，在仓库
`Settings → Pages → Build and deployment` 中将 Source 设为 `GitHub Actions`。

站点默认地址：<https://reknottycat.github.io/cad-translation-web/>

## 文件说明

- `index.html`：语义化页面结构与宣传文案。
- `styles.css`：响应式视觉样式、蓝图界面和动效。
- `script.js`：图纸双语对比、运行形态切换、复制命令和移动导航。
- `favicon.svg`：站点图标。
- `.nojekyll`：让 GitHub Pages 按原样发布静态资源。

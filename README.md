# shareqr

[![PyPI](https://img.shields.io/pypi/v/shareqr)](https://pypi.org/project/shareqr/)
[![AUR](https://img.shields.io/aur/version/shareqr)](https://aur.archlinux.org/packages/shareqr/)

A simple and fast command-line tool to share files from your computer to any device using a QR code.

## Features

*   **Share Multiple Files:** Share one or more files at once.
*   **QR Code Access:** Instantly generates a QR code in your terminal for easy access on mobile devices.
*   **Web Server:** Starts a temporary local web server to host the files.
*   **Public URL:** Uses an SSH tunnel to create a public URL, making your files accessible from anywhere.
*   **ZIP Bundling:** Automatically bundles multiple files into a single ZIP archive for convenient downloading.

## Installation

### From PyPI

```bash
pip install shareqr
```

### From Source

1.  Clone the repository:
    ```bash
    git clone https://github.com/AniruthKarthik/shareqr.git
    cd shareqr
    ```
2.  Install the project in editable mode:
    ```bash
    pip install .
    ```

## Usage

To share one or more files, simply run `shareqr` with the paths to the files you want to share.

```bash
shareqr <file_path1> [<file_path2> ...]
```

### Example

To share a file named `document.pdf` and an image named `photo.jpg`:

```bash
shareqr document.pdf photo.jpg
```

The tool will start a web server, generate a public URL, and display a QR code in your terminal. Scan the QR code with your phone or tablet to open the download page in your browser.

The download page will list all the shared files and provide a single button to download them all as a ZIP archive.

Press `Ctrl+C` to stop the server and close the public URL.

## How It Works

shareqr starts a local HTTP server on your machine to serve the files. It then uses an SSH reverse tunnel to expose this local server to the internet through a public URL. Finally, it generates a QR code for this URL so you can easily open it on another device.

## Author

*   **Aniruth Karthik** - [AniruthKarthik](https://github.com/AniruthKarthik)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
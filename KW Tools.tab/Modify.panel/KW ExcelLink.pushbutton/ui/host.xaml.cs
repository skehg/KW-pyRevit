using System;
using Microsoft.Web.WebView2.Core;

namespace KWExcelLink
{
    // Companion WebView2 bridge source. The pyRevit entry point wires the same
    // message contract from IronPython so this source does not require compilation.
    public sealed class ExcelLinkWebBridge
    {
        public event Action<string> MessageReceived;

        public void Attach(CoreWebView2 core)
        {
            if (core == null)
                throw new ArgumentNullException("core");

            core.WebMessageReceived += OnWebMessageReceived;
        }

        private void OnWebMessageReceived(
            object sender,
            CoreWebView2WebMessageReceivedEventArgs args)
        {
            var handler = MessageReceived;
            if (handler != null)
                handler(args.WebMessageAsJson);
        }
    }
}

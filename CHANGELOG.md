# Changelog

Unreleased
- New: Borrow and cancel holds
- New: Fave magazines to monitor for new issues
- Integration with the [OverDrive Link plugin](https://www.mobileread.com/forums/showthread.php?t=187919): If an existing book has a matching OverDrive link and no formats, the loan download will be added to the book.
- Fix issue with converted `.acsm` downloads not having metadata
- Add option to View in OverDrive
- Sort titles with sort name instead of name
- Colored icons
- Implement loading overlay

Version 0.1.3 - 2023-07-03
- New: View loans in Libby (from context/right-click menu)
- New: Return loans (from context/right-click menu)
- New: Auto tag downloaded books
- Properly display Checkout Date according to preferences
- Increase concurrent loan downloads
- Main loans window is now modal
- Use icons instead of unicode symbols for buttons
- Removed Verbose Logs option from config
- Improved implementation for Download, Refresh buttons
- Detect invalid Libby setup code format early
- Reduced zip file size by removing unneeded translation files

Version 0.1.2 - 2023-07-02
- Plugin now remembers the size of the main loans window

Version 0.1.1 - 2023-07-01
- Plugin no longer locks up while fetching loan data

Version 0.1.0 - 2023-07-01
- First release

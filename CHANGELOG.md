# Changelog

Unreleased
- New: Option to "Borrow and Download" from the Borrow button for loans/magazines
- New: Edit a hold to suspend or delay delivery
- Disable Borrow button if a magazine issue is already borrowed
- Generate the `odid` identifier for a new download if user has the  [OverDrive Link plugin](https://www.mobileread.com/forums/showthread.php?t=187919) installed
- New: Option to mark books that have been updated with a new format
- Fix title matching for book that has a subtitle
- Fix regression where generated magazines temp files were not being properly deleted
- Fix layout wonkiness
- Localize date values
- Switch to using svg image files for icons, so plugin zip is now smaller

Version 0.1.4 - 2023-07-10
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

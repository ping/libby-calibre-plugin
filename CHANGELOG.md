# Changelog

Unrelease
- New: Display number of available holds in the Holds tab text
- New: Last used tab will be opened by default
- New: Disable borrow button if limits for the card has been reached
- Improvement: Display hold wait information in status bar
- Improvement: Try to reduce the amount of sensitive data logged
- Fix: Holds view default sort
- Fix: Display on loans that are due soon
- Fix: Handling of job errors
- Fix: Compat problems for calibre 6.9 and possibly older

- Version 0.1.6 - 2023-07-21
- Fix: Error if loan was sent to Kindle
- Fix: Issue for Windows where window size is not restored properly
- New: Option to disable updating of existing empty books
- New: Indicate if loan is a skip-the-line checkout
- Improvement: Update more book metadata from loan details
- Improvement: Match empty books for update using title/ISBN/ASIN even if OverDrive Link Integration is not enabled
- Improvement: Make UI more keyboard navigable

Version 0.1.5 - 2023-07-15
- New: Option to "Borrow and Download" from the Borrow button for loans/magazines
- New: Edit a hold to suspend or delay delivery
- New: Option to mark books that have been updated with a new format
- New: Option to exclude/include empty books when hiding titles already in library
- Disable Borrow button if a magazine issue is already borrowed
- Generate the `odid` identifier for a new download if user has the  [OverDrive Link plugin](https://www.mobileread.com/forums/showthread.php?t=187919) installed
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

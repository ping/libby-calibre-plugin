# Changelog

Unreleased
- New: Rename a card

Version 0.1.9 - 2023-09-19
- Fix: Error on launch for calibre <6.2.0
- New: Option to disable the Magazines tab
- Improve: Convert configuration UI to use tabs so that there is room for more settings in the future

Version 0.1.8 - 2023-09-05
- New: Advance search mode
- New: Simple filter for titles and names in the Loans/Holds/Magazines/Cards tabs
- New: Copy the Libby share link for a book
- New: Verify a card
- New: Generate a setup code (for another device)
- Improve: Display linked identifiers, subjects in Book Details
- Improve: Infrequently changed data like libraries are now cached to give sync a small speed bump
- Improve: Card image in cards tab is not fuzzy anymore
- Fix: Borrowing with a card that has no lending period preference
- Fix: Display of rating in book details
- Fix: Properly update empty book without any identifiers (ref #8)
- Fix: Duplicate condition when finding a book in calibre library
- Fix: Error when library does not have default colours setup (ref #11)

Version 0.1.7 - 2023-08-20
- New: If "Include titles without downloadable formats" is enabled, titles that do not have a downloadable format will be shown. In addition, when the title is chosen for download, the plugin will create an Empty Book
- New: Read with Kindle option is available for loans that are available as Kindle books and not already format-locked
- New: Search tab that provides a basic search function across your libraries
- New: View book details by double-clicking on the row
- New: Cards tab that gives an overview of your linked cards
- New: Custom columns to store borrowed/due dates, and loan type (calibre>=5.35.0)
- New: Renew/place hold for an expiring loan
- New: Display number of available holds in the Holds tab text
- New: Last used tab will be opened by default
- New: Disable borrow button if limits for the card has been reached
- New: Compatible with calibre 5.34.0 and newer
- Improvement: Display hold wait information in status bar
- Improvement: Try to reduce the amount of sensitive data logged
- Improvement: Handle unexpected errors explicitly so that errors popups don't end up behind plugin UI
- Fix: Holds view default sort
- Fix: Display of loans that are due soon

Version 0.1.6 - 2023-07-21
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

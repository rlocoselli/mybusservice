heroku_files=$(heroku run ls '*.yml' | tail -n +4)

# Loop through each file and copy it to the local directory
for file in $heroku_files; do
    echo "Copying $file..."
    heroku ps:copy $file
done

echo "Done."
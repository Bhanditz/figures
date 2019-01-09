
Building a Figures release

The general process is to build the assets in develop branch, then PR to master




clone figures
change branch to develop
install environment package dependencies
* JavaScript
* Python


cd frontend
npm install
npm run build

delete the old files, add new and modified ones. You'll see something like


```

(figures) opus:figures jbaldwin$ git st
On branch release_0_1_5
Changes not staged for commit:
  (use "git add/rm <file>..." to update what will be committed)
  (use "git checkout -- <file>..." to discard changes in working directory)

	modified:   figures/static/figures/asset-manifest.json
	modified:   figures/static/figures/index.html
	modified:   figures/static/figures/service-worker.js
	deleted:    figures/static/figures/static/js/main.a5128534.js
	deleted:    figures/static/figures/static/js/main.a5128534.js.map
	modified:   figures/webpack-stats.json

Untracked files:
  (use "git add <file>..." to include in what will be committed)

	figures/static/figures/static/js/main.0da4d024.js
	figures/static/figures/static/js/main.0da4d024.js.map

no changes added to commit (use "git add" and/or "git commit -a")
```

Commit the changes


Create new release version
- bump the version in setup.py
- Add new entry for CHANGELOG.md

# create and test the updated package

Make sure tests pass (The PR should do that)


# Tagging a release

After PR is merged to master, tag the version with an annotated tag, making sure
that you have the version number correct

```
git tag -a 1.0.1 -m "tag message"
git push origin 1.0.1
```

This will bring up an editor to fill in the commit message. Provide details you
would want if you were a member of the Open edX community and needed to understand
what is in the release. See past examples in the [Figures releases page on Github](https://github.com/appsembler/figures/releases/).

Click on one (or more) of the tags to see the commit messages

In general, you want to document what was changed at a high level

Structure of the message
First line the version
Followed by bullets highlighting the new behavior or if just one line, no bullet

# Release

## Build the PyPI package



## Deploy to PyPI

We go through this process twice

* PyPI test server
* PyPI production server

A specific filename can only be pushed once. This is why it is important to
make sure the bundle is valid before pushing to production PyPI


## Test package

After you push to 
```
pip install figures==0.1.6
```

```
make clean_python_buld
make build_python
```

# Load Twine credentials

```
export TWINE_USERNAME="your-pypi-username"
export TWINE_PASSWORD="your-pypi-password"
```

# Run twine

First check the Python distributions:
```
make twine_check
```

If passes, push to PyPI testing (test.pypi.org)

```
twine push test
```

# Test the package

Currently manual testing is needed for the installation and integration validation

You created distribution packages in the Figures `./dist/` folder. Make these files available to the Vagrant VM you are using to test the release.

* Shell into the vm
* Become the edxapp user
* `pip uninstall figures`
* `pip install path/to/Figures-0.1.6.tar.gz`

## Spot testing

* Make sure the React UI works
* Make sure the API works
* Run the pipeline Django management command

## Deeper testing

_This is a wish list_

* Rich data
* Automate API testing 
* Security inspection
* Pipeline diagnostics



# Testing in devstack

In an Open edX devstack

* Uninstall Figures if already installed
* pip install Figures. This should pull from PyPI. Make sure the version is the
  latest you pushed to PyPI



commit changes
push to pr from develop to master
check that it passes


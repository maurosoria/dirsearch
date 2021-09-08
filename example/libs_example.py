import dirsearch.libdirsearch as lds

class DirFoundHandle(lds.DirFoundHandler):
    def found_dir(self, path, reponse, full_url, added_to_queue):
        print(path)
        if (reponse.redirect):
            print(reponse.redirect)

    def config_data(self, extensions, prefixes, suffixes, threads_count, dictionary, httpmethod):
        print(
            ', '.join(extensions),
            ', '.join(prefixes),
            ', '.join(suffixes),
            str(threads_count),
            str(len(dictionary)),
            str(httpmethod),
        )


dfh = DirFoundHandle()

dirsearch = lds.dirsearch(dfh)

args = ["-u", "http://sneaindia.com/"]

dirsearch.run(args)

print(dfh.dirs)
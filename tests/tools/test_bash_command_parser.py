import unittest

from micro_x_agent_loop.tools.bash_command_parser import extract_mutated_paths


class ExtractMutatedPathsTests(unittest.TestCase):
    # ---- Redirects --------------------------------------------------------

    def test_output_redirect(self) -> None:
        self.assertEqual(["out.txt"], extract_mutated_paths("echo hi > out.txt"))

    def test_append_redirect(self) -> None:
        self.assertEqual(["log.txt"], extract_mutated_paths("echo hi >> log.txt"))

    def test_redirect_to_dev_null_ignored(self) -> None:
        self.assertEqual([], extract_mutated_paths("some_cmd > /dev/null"))

    def test_redirect_to_nul_ignored(self) -> None:
        self.assertEqual([], extract_mutated_paths("some_cmd > NUL"))

    def test_stderr_redirect(self) -> None:
        self.assertEqual(["err.log"], extract_mutated_paths("cmd 2> err.log"))

    # ---- rm / del / rmdir -------------------------------------------------

    def test_rm_single(self) -> None:
        self.assertEqual(["foo.txt"], extract_mutated_paths("rm foo.txt"))

    def test_rm_multiple(self) -> None:
        result = extract_mutated_paths("rm -f a.txt b.txt")
        self.assertIn("a.txt", result)
        self.assertIn("b.txt", result)

    def test_rmdir(self) -> None:
        self.assertEqual(["mydir"], extract_mutated_paths("rmdir mydir"))

    def test_del_windows(self) -> None:
        self.assertEqual(["file.tmp"], extract_mutated_paths("del file.tmp"))

    # ---- mv / move --------------------------------------------------------

    def test_mv(self) -> None:
        result = extract_mutated_paths("mv src.txt dst.txt")
        self.assertIn("src.txt", result)
        self.assertIn("dst.txt", result)

    def test_move_windows(self) -> None:
        result = extract_mutated_paths("move old.txt new.txt")
        self.assertIn("old.txt", result)
        self.assertIn("new.txt", result)

    # ---- cp / copy --------------------------------------------------------

    def test_cp_destination_only(self) -> None:
        result = extract_mutated_paths("cp src.txt dst.txt")
        self.assertEqual(["dst.txt"], result)

    def test_copy_windows(self) -> None:
        result = extract_mutated_paths("copy src.txt dst.txt")
        self.assertEqual(["dst.txt"], result)

    # ---- touch / mkdir ----------------------------------------------------

    def test_touch(self) -> None:
        self.assertEqual(["new.txt"], extract_mutated_paths("touch new.txt"))

    def test_mkdir(self) -> None:
        self.assertEqual(["subdir"], extract_mutated_paths("mkdir subdir"))

    def test_mkdir_with_flag(self) -> None:
        self.assertEqual(["a/b/c"], extract_mutated_paths("mkdir -p a/b/c"))

    # ---- tee --------------------------------------------------------------

    def test_tee(self) -> None:
        self.assertEqual(["out.log"], extract_mutated_paths("tee out.log"))

    def test_tee_append(self) -> None:
        self.assertEqual(["out.log"], extract_mutated_paths("tee -a out.log"))

    def test_tee_multiple(self) -> None:
        result = extract_mutated_paths("tee file1 file2")
        self.assertIn("file1", result)
        self.assertIn("file2", result)

    # ---- sed -i -----------------------------------------------------------

    def test_sed_inplace(self) -> None:
        result = extract_mutated_paths("sed -i 's/a/b/g' config.ini")
        self.assertIn("config.ini", result)

    def test_sed_inplace_suffix(self) -> None:
        result = extract_mutated_paths("sed -i.bak 's/a/b/g' config.ini")
        self.assertIn("config.ini", result)

    # ---- chmod / chown / chgrp -------------------------------------------

    def test_chmod(self) -> None:
        result = extract_mutated_paths("chmod 755 script.sh")
        self.assertIn("script.sh", result)

    def test_chown(self) -> None:
        result = extract_mutated_paths("chown user:group file.txt")
        self.assertIn("file.txt", result)

    def test_chgrp(self) -> None:
        result = extract_mutated_paths("chgrp staff file.txt")
        self.assertIn("file.txt", result)

    # ---- Chained commands -------------------------------------------------

    def test_chain_with_semicolon(self) -> None:
        result = extract_mutated_paths("echo a > x.txt; rm y.txt")
        self.assertIn("x.txt", result)
        self.assertIn("y.txt", result)

    def test_chain_with_and(self) -> None:
        result = extract_mutated_paths("mkdir dir1 && touch dir1/file.txt")
        self.assertIn("dir1", result)
        self.assertIn("dir1/file.txt", result)

    def test_pipe_with_tee(self) -> None:
        result = extract_mutated_paths("cat input.txt | tee output.txt")
        self.assertIn("output.txt", result)

    # ---- Read-only commands → [] -----------------------------------------

    def test_ls_returns_empty(self) -> None:
        self.assertEqual([], extract_mutated_paths("ls -la"))

    def test_git_status_returns_empty(self) -> None:
        self.assertEqual([], extract_mutated_paths("git status"))

    def test_cat_returns_empty(self) -> None:
        self.assertEqual([], extract_mutated_paths("cat foo.txt"))

    def test_echo_no_redirect_returns_empty(self) -> None:
        self.assertEqual([], extract_mutated_paths("echo hello world"))

    def test_grep_returns_empty(self) -> None:
        self.assertEqual([], extract_mutated_paths("grep -r pattern src/"))

    # ---- Edge cases -------------------------------------------------------

    def test_empty_string(self) -> None:
        self.assertEqual([], extract_mutated_paths(""))

    def test_whitespace_only(self) -> None:
        self.assertEqual([], extract_mutated_paths("   "))

    def test_malformed_quotes(self) -> None:
        # Should not raise — returns best-effort or []
        result = extract_mutated_paths("echo 'unbalanced > out.txt")
        self.assertIsInstance(result, list)

    def test_deduplicates_paths(self) -> None:
        result = extract_mutated_paths("touch f.txt; touch f.txt")
        self.assertEqual(["f.txt"], result)


if __name__ == "__main__":
    unittest.main()
